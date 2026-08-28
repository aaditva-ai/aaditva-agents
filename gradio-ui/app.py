import logging
import os
import re
import time
import uuid
import json
import base64
import tempfile
import requests
import gradio as gr
import vertexai
from vertexai.preview import reasoning_engines
from vertexai import Client
from google.cloud import storage
import google.auth
from google.auth.transport.requests import Request
from datetime import timedelta
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from the project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
PROJECT_NUMBER = os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER")
LOCATION = os.getenv("LOCATION", "us-central1")
AGENT_ENGINE_ID = os.getenv("AGENT_ENGINE_ID")
GCS_IMAGES_BUCKET = os.getenv("GCS_IMAGES_BUCKET")
SIGNING_SA = os.getenv("SIGNING_SERVICE_ACCOUNT")

ARTIFACTS_DIR = os.path.join(tempfile.gettempdir(), "aaditva_artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# Cache for signed URLs to avoid redundant calls
SIGNED_URL_CACHE = {}

def save_artifact_to_file(filename, data, mime="image/png"):
    """Decode artifact bytes/base64 and save to a local temporary file for Gradio."""
    try:
        if isinstance(data, str):
            cleaned = data.strip().replace("\n", "").replace("\r", "")
            if "," in cleaned and "base64" in cleaned.split(",")[0]:
                cleaned = cleaned.split(",", 1)[1]
            raw_bytes = base64.b64decode(cleaned)
        elif isinstance(data, bytes):
            raw_bytes = data
        else:
            return None
        file_path = os.path.join(ARTIFACTS_DIR, filename)
        with open(file_path, "wb") as f:
            f.write(raw_bytes)
        return file_path
    except Exception as e:
        logger.error(f"Error saving artifact {filename}: {e}")
        return None

def get_local_image_for_gcs(gcs_uri):
    """Download GCS image to local cache file if signing is not available."""
    try:
        if not gcs_uri.startswith("gs://"):
            return None
        without_prefix = gcs_uri[len("gs://"):]
        bucket_name, blob_path = without_prefix.split("/", 1)
        filename = blob_path.split("/")[-1]
        local_path = os.path.join(ARTIFACTS_DIR, f"gcs_{filename}")
        if os.path.exists(local_path):
            return local_path
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.download_to_filename(local_path)
        return local_path
    except Exception as e:
        logger.debug(f"Could not download {gcs_uri} locally: {e}")
        return None

def get_signed_url(gcs_uri):
    """Generate a signed URL for a GCS URI."""
    if not gcs_uri.startswith("gs://"):
        return gcs_uri
        
    if gcs_uri in SIGNED_URL_CACHE:
        return SIGNED_URL_CACHE[gcs_uri]
        
    try:
        # gs://bucket/path
        without_prefix = gcs_uri[len("gs://"):]
        bucket_name, blob_path = without_prefix.split("/", 1)
        
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        # Try to use SA email for signing
        sa_email = SIGNING_SA
        if not sa_email:
            try:
                credentials, _ = google.auth.default()
                sa_email = getattr(credentials, "service_account_email", None)
            except:
                pass
        
        # Fallback to metadata server if we are on GCP
        if not sa_email or sa_email == "default":
             import urllib.request
             try:
                 req = urllib.request.Request(
                     "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
                     headers={"Metadata-Flavor": "Google"},
                 )
                 sa_email = urllib.request.urlopen(req, timeout=1).read().decode()
             except:
                 pass

        try:
            if sa_email and sa_email != "default":
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(hours=1),
                    method="GET",
                    service_account_email=sa_email
                )
            else:
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(hours=1),
                    method="GET"
                )
            SIGNED_URL_CACHE[gcs_uri] = signed_url
            return signed_url
        except Exception as sign_err:
            print(f"Signing failed for {gcs_uri}: {sign_err}")
            # Fallback: public URL if bucket is public (often not, but better than gs://)
            public_url = f"https://storage.googleapis.com/{bucket_name}/{blob_path}"
            return public_url
            
    except Exception as e:
        print(f"Error in get_signed_url for {gcs_uri}: {e}")
        return gcs_uri

def process_text(text):
    """Detect GCS URIs and HTTPS storage URLs and ensure they are rendered as images."""
    if not text:
        return ""
        
    # 1. Handle gs:// URIs - replace with Markdown images if not already replaced
    # Pattern matches gs:// URIs that are NOT inside backticks or already in a markdown image
    gcs_uri_pattern = r"(?<![`!(])gs://[a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_./%]+"
    
    def gcs_replacer(match):
        uri = match.group(0)
        url = get_signed_url(uri)
        if url.startswith("http") and not url.startswith("https://storage.googleapis.com"):
            return f"\n\n![Image]({url})\n\n*Source: {uri}*\n\n"
        local_path = get_local_image_for_gcs(uri)
        if local_path:
            return f"\n\n![Image]({local_path})\n\n*Source: {uri}*\n\n"
        if url.startswith("http"):
            return f"\n\n![Image]({url})\n\n*Source: {uri}*\n\n"
        return uri

    # Replace gs:// URIs with embedded images
    text = re.sub(gcs_uri_pattern, gcs_replacer, text)
    
    # 2. Handle GCS HTTPS links that should be images but are links [label](url)
    storage_http_link_pattern = r"(?<!\!)\[([^\]]+)\]\((https://storage\.googleapis\.com/[^\)]+)\)"
    text = re.sub(storage_http_link_pattern, r"![\1](\2)", text)
    
    # 3. Handle plain GCS HTTPS URLs (not in markdown)
    storage_http_url_pattern = r"(?<![`!(\[])https://storage\.googleapis\.com/[a-zA-Z0-9\-_./%?=&]+"
    def http_gcs_replacer(match):
        url = match.group(0)
        return f"\n\n![Image]({url})\n\n"
    text = re.sub(storage_http_url_pattern, http_gcs_replacer, text)
    
    return text

def fetch_artifact(agent_url, app_name, user_id, session_id, filename, version):
    """Fetch an artifact's content from the ADK server."""
    url = f"{agent_url}/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{filename}"
    params = {"version": version}
    try:
        # Retry once if it fails, as there might be a tiny race condition on the server
        for attempt in range(2):
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                part = resp.json()
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data:
                    data = inline_data.get("data")
                    mime = inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png"
                    if data:
                        # Ensure no weird whitespace in base64
                        return data.strip().replace("\n", "").replace("\r", ""), mime
            if attempt == 0:
                import time
                time.sleep(0.3)
    except Exception as e:
        print(f"Error fetching artifact {filename}: {e}")
    return None, None

RECONNECT_MAX_ATTEMPTS = 3
RECONNECT_DELAYS = (1, 2, 4)


def _try_once(connect_fn):
    """Call `connect_fn()`, returning `(result, None)` on success or `(None, exception)` on failure."""
    try:
        return connect_fn(), None
    except Exception as e:
        return None, e


def stream_chat(message, history, mode, agent_url, remote_engine_id, session_id=None):
    user_id = "gradio-user"
    if callable(session_id):
        try:
            session_id = session_id()
        except Exception:
            session_id = None
    if not session_id or not isinstance(session_id, str):
        session_id = str(uuid.uuid4())
    
    # State for multiple bubbles
    bubbles = []
    full_text = ""
    finalized_text_len = 0
    current_artifacts = ""
    running_tools = {} # id -> name
    completed_tools = []
    
    # List of known specialist agents to show with gear icon
    AGENT_NAMES = ["brand_strategist", "copywriter", "designer", "critic", "project_manager", "creative_director"]
    def get_tool_icon(name, is_running=False):
        icon = "⚙️" if name.lower() in AGENT_NAMES else "🛠️"
        if is_running:
            return f'<span class="spinning-gear" style="display: inline-block; animation: spin 2s linear infinite; transform-origin: center center;">{icon}</span>'
        return icon

    def get_current_bubbles(is_typing=False):
        res = bubbles.copy()
        
        # 1. Status chips
        chips = [f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]
        chips += [f"**[ {get_tool_icon(n, is_running=True)} {n} ]**" for n in running_tools.values()]
        
        if chips:
            status_msg = " ".join(chips)
            res.append(status_msg)
            
        # 2. Current text part
        text_part = full_text[finalized_text_len:]
        if text_part.strip():
            msg = process_text(text_part.strip())
            if is_typing:
                msg += "\n\n⌛ *Agent is typing...*"
            res.append(msg)
        elif is_typing and not chips:
            res.append("⌛ *Agent is typing...*")
            
        return res

    yield ["⏳ Connecting to agent..."]
    
    # Robustly handle message if it's a list of parts (Gradio 5 format)
    if isinstance(message, list):
        message = "".join([p.get("text", "") for p in message if isinstance(p, dict) and p.get("type") == "text"])
    
    if mode == "remote":
        effective_engine_id = (remote_engine_id.strip() if remote_engine_id else "") or AGENT_ENGINE_ID or os.getenv("AGENT_ENGINE_ID", "")
        effective_project_id = PROJECT_ID or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
        
        if not effective_project_id or not effective_engine_id:
            yield ["❌ Error: GOOGLE_CLOUD_PROJECT or Agent Engine ID not set."]
            return
            
        target_project = effective_project_id

        def _connect_remote():
            logger.info(f"Initializing Vertex AI with project={target_project}, location={LOCATION}")
            vertexai.init(project=target_project, location=LOCATION)
            client = Client(project=target_project, location=LOCATION)

            if effective_engine_id.startswith("projects/"):
                resource_name = effective_engine_id
            else:
                resource_name = f"projects/{target_project}/locations/{LOCATION}/reasoningEngines/{effective_engine_id}"

            logger.info(f"Connecting to reasoning engine: {resource_name}")
            return client.agent_engines.get(name=resource_name)

        agent_engine = None
        conn_error = None
        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            agent_engine, conn_error = _try_once(_connect_remote)
            if agent_engine is not None:
                break
            if attempt < RECONNECT_MAX_ATTEMPTS - 1:
                yield ["🔄 Reconnecting to agent..."]
                time.sleep(RECONNECT_DELAYS[attempt])

        if agent_engine is None:
            yield [f"❌ Error: {conn_error}"]
            return

        logger.info(f"Successfully connected to reasoning engine, using session_id={session_id}")

        try:
            for event in agent_engine.stream_query(user_id=user_id, session_id=session_id, message=message):
                # 1. Tool Call Detection
                if any(k in event for k in ["tool_calls", "tool_call", "function_calls", "function_call"]):
                    calls = event.get("tool_calls") or event.get("function_calls") or []
                    if not isinstance(calls, list):
                        calls = [event.get("tool_call") or event.get("function_call")]
                    for call in calls:
                        if call:
                            name = call.get("name", "tool")
                            call_id = call.get("id", str(uuid.uuid4()))
                            if call_id not in running_tools:
                                # Transition: finalize text before tool starts
                                text_part = full_text[finalized_text_len:] + current_artifacts
                                if text_part.strip():
                                    bubbles.append(process_text(text_part.strip()))
                                    finalized_text_len = len(full_text)
                                    current_artifacts = ""
                                
                                # Finalize completed chips if any (sequential tools)
                                if completed_tools:
                                    bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                    completed_tools = []
                                    
                                running_tools[call_id] = name
                
                # Nested content parts for tool calls
                if "content" in event and "parts" in event["content"]:
                    for part in event["content"]["parts"]:
                        if any(k in part for k in ["function_call", "functionCall"]):
                            call = part.get("function_call") or part.get("functionCall")
                            name = call.get("name", "tool")
                            call_id = call.get("id", str(uuid.uuid4()))
                            if call_id not in running_tools:
                                text_part = full_text[finalized_text_len:] + current_artifacts
                                if text_part.strip():
                                    bubbles.append(process_text(text_part.strip()))
                                    finalized_text_len = len(full_text)
                                    current_artifacts = ""
                                
                                # Finalize completed chips
                                if completed_tools:
                                    bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                    completed_tools = []
                                    
                                running_tools[call_id] = name

                # 2. Tool Response Detection
                if any(k in event for k in ["tool_responses", "tool_response", "function_responses", "function_response"]):
                    resps = event.get("tool_responses") or event.get("function_responses") or []
                    if not isinstance(resps, list):
                        resps = [event.get("tool_response") or event.get("function_response")]
                    for resp in resps:
                        if resp:
                            call_id = resp.get("id")
                            if call_id in running_tools:
                                completed_tools.append(running_tools.pop(call_id))
                            elif running_tools:
                                completed_tools.append(running_tools.popitem()[1])
                
                # Nested content parts for responses
                if "content" in event and "parts" in event["content"]:
                    for part in event["content"]["parts"]:
                        if any(k in part for k in ["function_response", "functionResponse"]):
                            resp = part.get("function_response") or part.get("functionResponse")
                            call_id = resp.get("id")
                            if call_id in running_tools:
                                completed_tools.append(running_tools.pop(call_id))
                            elif running_tools:
                                completed_tools.append(running_tools.popitem()[1])

                # 3. Text & Artifact Processing
                if "content" in event and "parts" in event["content"]:
                    current_event_text = ""
                    for part in event["content"]["parts"]:
                        if "text" in part:
                            current_event_text += part["text"]
                        elif "inline_data" in part or "inlineData" in part:
                            inline = part.get("inline_data") or part.get("inlineData")
                            data = inline.get("data")
                            mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                            if data:
                                fname = f"image_{uuid.uuid4().hex[:6]}.png"
                                file_path = save_artifact_to_file(fname, data, mime)
                                if file_path:
                                    # Flush any text seen earlier in this same event so it
                                    # is finalized *before* the image bubble, not after.
                                    if current_event_text:
                                        if len(current_event_text) > len(full_text) and current_event_text.startswith(full_text):
                                            full_text = current_event_text
                                        elif not full_text.endswith(current_event_text):
                                            full_text += current_event_text
                                        current_event_text = ""
                                    text_part = full_text[finalized_text_len:]
                                    if text_part.strip():
                                        bubbles.append(process_text(text_part.strip()))
                                        finalized_text_len = len(full_text)
                                    if completed_tools:
                                        bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                        completed_tools = []
                                    bubbles.append({"path": file_path, "alt_text": fname, "type": "file"})
                    
                    if current_event_text:
                        # Finalize chips bubble if we have new text and no active tools
                        if not running_tools and completed_tools:
                            bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                            completed_tools = []
                        
                        if len(current_event_text) > len(full_text) and current_event_text.startswith(full_text):
                            full_text = current_event_text
                        elif not full_text.endswith(current_event_text):
                            full_text += current_event_text
                
                yield get_current_bubbles(is_typing=event.get("partial", False))
        except Exception as e:
            yield [f"❌ Error in remote streaming: {str(e)}"]
    else:
        # Local mode
        app_name = remote_engine_id if remote_engine_id else "creative_director"
        agent_url = agent_url.strip().rstrip("/")
        if not message or not message.strip():
            yield ["⚠️ Please enter a message."]
            return
            
        session_state = {"session_id": session_id}

        def _connect_local():
            sid = session_state["session_id"]
            session_url = f"{agent_url}/apps/{app_name}/users/{user_id}/sessions"
            try:
                check_resp = requests.get(f"{session_url}/{sid}", timeout=5)
                if check_resp.status_code != 200:
                    create_resp = requests.post(session_url, json={"session_id": sid}, timeout=5)
                    if create_resp.status_code in (200, 201):
                        session_state["session_id"] = create_resp.json().get("id", sid)
            except Exception as se:
                logger.debug(f"Session init check warning: {se}")

            url = f"{agent_url}/run_sse"
            payload = {
                "app_name": app_name,
                "user_id": user_id,
                "session_id": session_state["session_id"],
                "new_message": {"role": "user", "parts": [{"text": message}]},
                "streaming": True
            }

            resp = requests.post(url, json=payload, stream=True, timeout=300)
            if resp.status_code != 200:
                raise RuntimeError(f"Local agent status {resp.status_code}")
            return resp

        response = None
        conn_error = None
        for attempt in range(RECONNECT_MAX_ATTEMPTS):
            response, conn_error = _try_once(_connect_local)
            if response is not None:
                break
            if attempt < RECONNECT_MAX_ATTEMPTS - 1:
                yield ["🔄 Reconnecting to agent..."]
                time.sleep(RECONNECT_DELAYS[attempt])

        if response is None:
            yield [f"❌ Error: {conn_error}"]
            return

        session_id = session_state["session_id"]

        try:
            processed_artifacts = set()
            for line in response.iter_lines():
                if line:
                    line_text = line.decode("utf-8")
                    if line_text.startswith("data: "):
                        try:
                            data = json.loads(line_text[6:])
                            
                            # 1. Tool Call Detection
                            if any(k in data for k in ["toolCall", "functionCall", "tool_call"]):
                                call = data.get("toolCall") or data.get("functionCall") or data.get("tool_call")
                                call_id = data.get("id", str(uuid.uuid4()))
                                name = call.get("name", "tool")
                                if call_id not in running_tools:
                                    text_part = full_text[finalized_text_len:] + current_artifacts
                                    if text_part.strip():
                                        bubbles.append(process_text(text_part.strip()))
                                        finalized_text_len = len(full_text)
                                        current_artifacts = ""
                                    
                                    # Finalize completed chips
                                    if completed_tools:
                                        bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                        completed_tools = []
                                        
                                    running_tools[call_id] = name
                            
                            # Nested parts tool calls
                            if "content" in data and "parts" in data["content"]:
                                for part in data["content"]["parts"]:
                                    if any(k in part for k in ["functionCall", "function_call"]):
                                        call = part.get("functionCall") or part.get("function_call")
                                        call_id = call.get("id", str(uuid.uuid4()))
                                        name = call.get("name", "tool")
                                        if call_id not in running_tools:
                                            text_part = full_text[finalized_text_len:] + current_artifacts
                                            if text_part.strip():
                                                bubbles.append(process_text(text_part.strip()))
                                                finalized_text_len = len(full_text)
                                                current_artifacts = ""
                                            
                                            # Finalize completed chips
                                            if completed_tools:
                                                bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                                completed_tools = []
                                                
                                            running_tools[call_id] = name
                            
                            # 2. Tool Response Detection
                            if any(k in data for k in ["toolResponse", "functionResponse", "tool_response"]):
                                call_id = data.get("id")
                                if call_id in running_tools:
                                    completed_tools.append(running_tools.pop(call_id))
                                elif running_tools:
                                    completed_tools.append(running_tools.popitem()[1])

                            if "content" in data and "parts" in data["content"]:
                                for part in data["content"]["parts"]:
                                    if any(k in part for k in ["functionResponse", "function_response"]):
                                        resp = part.get("functionResponse") or part.get("function_response")
                                        call_id = resp.get("id")
                                        if call_id in running_tools:
                                            completed_tools.append(running_tools.pop(call_id))
                                        elif running_tools:
                                            completed_tools.append(running_tools.popitem()[1])
                            
                            # 3. Artifact Detection
                            actions = data.get("actions", {})
                            artifact_delta = actions.get("artifactDelta", {}) or actions.get("artifact_delta", {})
                            if artifact_delta:
                                for filename, version in artifact_delta.items():
                                    artifact_key = f"{filename}_{version}"
                                    if artifact_key not in processed_artifacts:
                                        processed_artifacts.add(artifact_key)
                                        art_data, art_mime = fetch_artifact(agent_url, app_name, user_id, session_id, filename, version)
                                        if art_data:
                                            file_path = save_artifact_to_file(filename, art_data, art_mime)
                                            if file_path:
                                                text_part = full_text[finalized_text_len:]
                                                if text_part.strip():
                                                    bubbles.append(process_text(text_part.strip()))
                                                    finalized_text_len = len(full_text)
                                                if completed_tools:
                                                    bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                                    completed_tools = []
                                                bubbles.append({"path": file_path, "alt_text": filename, "type": "file"})
                                        else:
                                            bubbles.append(f"*Created artifact: {filename} (v{version})*")
                            
                            # 4. Text Processing
                            if "content" in data and "parts" in data["content"]:
                                current_event_text = ""
                                for part in data["content"]["parts"]:
                                    if "text" in part:
                                        current_event_text += part["text"]
                                    elif "inlineData" in part or "inline_data" in part:
                                        p = part.get("inlineData") or part.get("inline_data")
                                        d, m = p.get("data"), p.get("mimeType") or p.get("mime_type") or "image/png"
                                        if d:
                                            fname = f"artifact_{uuid.uuid4().hex[:6]}.png"
                                            file_path = save_artifact_to_file(fname, d, m)
                                            if file_path:
                                                # Flush any text seen earlier in this same event so it
                                                # is finalized *before* the image bubble, not after.
                                                if current_event_text:
                                                    if len(current_event_text) > len(full_text) and current_event_text.startswith(full_text):
                                                        full_text = current_event_text
                                                    elif not full_text.endswith(current_event_text):
                                                        full_text += current_event_text
                                                    current_event_text = ""
                                                text_part = full_text[finalized_text_len:]
                                                if text_part.strip():
                                                    bubbles.append(process_text(text_part.strip()))
                                                    finalized_text_len = len(full_text)
                                                if completed_tools:
                                                    bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                                    completed_tools = []
                                                bubbles.append({"path": file_path, "alt_text": fname, "type": "file"})
                                
                                if current_event_text:
                                    if not running_tools and completed_tools:
                                        bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                        completed_tools = []
                                    
                                    if data.get("partial"):
                                        full_text += current_event_text
                                    else:
                                        if current_event_text == full_text: pass
                                        elif len(current_event_text) > len(full_text) and current_event_text.startswith(full_text):
                                            full_text = current_event_text
                                        elif not full_text.endswith(current_event_text):
                                            full_text += current_event_text
                                            
                            elif "text" in data:
                                if not running_tools and completed_tools:
                                    bubbles.append(" ".join([f"**[ {get_tool_icon(n)} {n} ]**" for n in completed_tools]))
                                    completed_tools = []
                                if not full_text.endswith(data["text"]):
                                    full_text += data["text"]
                            
                            yield get_current_bubbles(is_typing=data.get("partial", False))
                            if data.get("turnComplete") or data.get("turn_complete") or data.get("endOfAgent") or data.get("end_of_agent"):
                                break
                        except json.JSONDecodeError: continue
        except Exception as e:
            yield [f"❌ Error in local streaming: {str(e)}"]

CUSTOM_CSS = """
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
.spinning-gear {
    display: inline-block;
    animation: spin 2s linear infinite;
    transform-origin: center center;
}
#submit_btn:disabled {
    position: relative;
    cursor: not-allowed;
}
#submit_btn:disabled:hover::after {
    content: "Midway prompts are currently unsupported. Use Clear Chat to cancel and start a new one.";
    position: absolute;
    bottom: 100%;
    right: 0;
    margin-bottom: 8px;
    width: 220px;
    padding: 8px 10px;
    background: #333;
    color: #fff;
    font-size: 0.8em;
    line-height: 1.3;
    border-radius: 6px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    z-index: 1000;
    white-space: normal;
    pointer-events: none;
}
"""

# Gradio UI with Blocks for custom layout
with gr.Blocks(title="Creative Director AI Studio") as demo:
    session_state = gr.State(lambda: str(uuid.uuid4()))
    with gr.Sidebar():
        gr.Markdown("## ⚙️ Connection Settings")
        gr.Markdown("Configure how the UI connects to the Creative Director agent.")
        
        default_mode = os.getenv("AGENT_MODE", "local").lower()
        if default_mode not in ["local", "remote"]:
            default_mode = "local"
        
        mode_toggle = gr.Radio(
            ["local", "remote"], 
            label="Connection Mode", 
            value=default_mode,
            info="Local uses ADK Web; Remote uses Vertex AI Agent Engine."
        )
        
        agent_url_input = gr.Textbox(
            label="Local Agent URL", 
            value=os.getenv("AGENT_URL", "http://127.0.0.1:8000"),
            visible=(default_mode == "local"),
            placeholder="http://127.0.0.1:8000"
        )
        
        engine_id_input = gr.Textbox(
            label="Vertex AI Engine ID", 
            value=AGENT_ENGINE_ID or os.getenv("AGENT_ENGINE_ID", ""),
            visible=(default_mode == "remote"),
            placeholder="projects/.../locations/.../reasoningEngines/..."
        )
        
        def update_visibility(mode, current_agent_url, current_engine_id):
            default_url = os.getenv("AGENT_URL", "http://127.0.0.1:8000")
            default_engine_id = AGENT_ENGINE_ID or os.getenv("AGENT_ENGINE_ID", "")
            return (
                gr.update(
                    visible=(mode == "local"),
                    value=current_agent_url if current_agent_url else default_url
                ),
                gr.update(
                    visible=(mode == "remote"),
                    value=current_engine_id if current_engine_id else default_engine_id
                )
            )
        
        mode_toggle.change(
            update_visibility, 
            inputs=[mode_toggle, agent_url_input, engine_id_input], 
            outputs=[agent_url_input, engine_id_input],
            queue=False,
            show_progress="hidden"
        )
        
        gr.HTML("<hr>")
        gr.Markdown("### 🛠️ Help")
        gr.Markdown("""
        - **Local**: Run `uv run adk web agents` in the project root.
        - **Remote**: Ensure you have authenticated with `gcloud auth application-default login`.
        """)

    with gr.Column():
        gr.HTML("""
        <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="font-size: 2.5em; margin-bottom: 0px;">🎨 Creative Director AI Studio</h1>
            <p style="font-size: 1.2em; color: #666; margin-top: 5px;">Orchestrate specialist agents to build complete marketing campaigns.</p>
        </div>
        """)
        
        chatbot = gr.Chatbot(
            height=650, 
            show_label=False, 
            avatar_images=(None, None),
            group_consecutive_messages=False,
        )
        
        with gr.Row():
            msg = gr.Textbox(
                placeholder="Describe the campaign you want to create...",
                label="Campaign Brief",
                scale=9,
                autofocus=True,
                show_label=False
            )
            submit_btn = gr.Button("🚀 Send", variant="primary", scale=1, elem_id="submit_btn")
        
        with gr.Row():
            clear_btn = gr.Button("🗑️ Clear Chat", size="sm")
        
        with gr.Accordion("📚 Inspiration & Examples", open=False):
            gr.Examples(
                examples=[
                    ["Create a complete Instagram campaign for a new eco-friendly smart water bottle targeting Gen Z."],
                    ["Develop a brand strategy and 3 social posts for a luxury minimalist watch brand."],
                    ["Research the competitive landscape for plant-based protein powders and write a campaign brief."],
                ],
                inputs=[msg]
            )

    def user_action(user_message, history):
        if not user_message:
            return "", history
        # Return in Gradio 5 format: content is a list of parts
        return "", history + [{"role": "user", "content": [{"text": user_message, "type": "text"}]}]

    def disable_inputs():
        # Disable the prompt box and Send button while a response is streaming.
        # Midway prompts aren't supported, so re-submitting must be blocked until
        # the current turn finishes (or clearly errors out).
        return gr.update(interactive=False), gr.update(interactive=False)

    def enable_inputs():
        # Re-enable the prompt box and Send button once the turn finishes end-to-end
        # or has clearly errored out.
        return gr.update(interactive=True), gr.update(interactive=True)

    def bot_action(history, mode, agent_url, engine_id, session_id):
        if not history or history[-1]["role"] != "user":
            return history, session_id
            
        if callable(session_id):
            try:
                session_id = session_id()
            except Exception:
                session_id = None
        if not session_id or not isinstance(session_id, str):
            session_id = str(uuid.uuid4())
            
        # Extract text from history parts
        user_message_parts = history[-1]["content"]
        user_message = ""
        if isinstance(user_message_parts, list):
            user_message = "".join([p.get("text", "") for p in user_message_parts if isinstance(p, dict) and p.get("type") == "text"])
        else:
            user_message = str(user_message_parts)
            
        # history already contains the user message as the last item
        base_history = history.copy()
        
        # Decide which ID to use based on mode
        # For local mode, we always use creative_director as requested
        app_name = "creative_director"
        engine_id_val = (engine_id.strip() if engine_id else "") or AGENT_ENGINE_ID or os.getenv("AGENT_ENGINE_ID", "")
        remote_id = engine_id_val if mode == "remote" else app_name
        
        try:
            for bubbles in stream_chat(user_message, base_history, mode, agent_url, remote_id, session_id=session_id):
                if not bubbles:
                    continue
                
                new_history = base_history.copy()
                for b in bubbles:
                    if isinstance(b, dict) and ("path" in b or b.get("type") == "file"):
                        filepath = b.get("path") or b.get("file", {}).get("path")
                        alt = b.get("alt_text") or ""
                        new_history.append({
                            "role": "assistant",
                            "content": [{
                                "path": filepath,
                                "type": "file",
                                "alt_text": alt
                            }]
                        })
                    else:
                        new_history.append({
                            "role": "assistant",
                            "content": [{
                                "text": str(b),
                                "type": "text"
                            }]
                        })
                yield new_history, session_id
        except Exception as e:
            new_history = base_history.copy()
            new_history.append({"role": "assistant", "content": [{"text": f"❌ **Error:** {str(e)}", "type": "text"}]})
            yield new_history, session_id

    # Event handlers
    msg.submit(user_action, [msg, chatbot], [msg, chatbot]).then(
        disable_inputs, None, [msg, submit_btn], queue=False, show_progress="hidden"
    ).then(
        bot_action, [chatbot, mode_toggle, agent_url_input, engine_id_input, session_state], [chatbot, session_state], concurrency_limit=None
    ).then(
        enable_inputs, None, [msg, submit_btn], queue=False, show_progress="hidden"
    )
    submit_btn.click(user_action, [msg, chatbot], [msg, chatbot]).then(
        disable_inputs, None, [msg, submit_btn], queue=False, show_progress="hidden"
    ).then(
        bot_action, [chatbot, mode_toggle, agent_url_input, engine_id_input, session_state], [chatbot, session_state], concurrency_limit=None
    ).then(
        enable_inputs, None, [msg, submit_btn], queue=False, show_progress="hidden"
    )
    clear_btn.click(
        lambda: ([], str(uuid.uuid4())), 
        inputs=None, 
        outputs=[chatbot, session_state], 
        queue=False, 
        show_progress="hidden"
    ).then(
        enable_inputs, None, [msg, submit_btn], queue=False, show_progress="hidden"
    )

if __name__ == "__main__":
    # Fix for Cloud Run: Ensure Gradio doesn't try to use a proxy for local checks
    os.environ["NO_PROXY"] = "localhost,127.0.0.1,0.0.0.0"
    
    demo.queue(default_concurrency_limit=None).launch(
        server_name="0.0.0.0", 
        server_port=int(os.getenv("PORT", 8080)),
        share=False,
        allowed_paths=[ARTIFACTS_DIR],
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS
    )
