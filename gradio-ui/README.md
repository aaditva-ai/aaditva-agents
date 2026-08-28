# Creative Director Gradio UI

This is a lightweight Gradio-based web frontend for the Creative Director agent.

## Local Setup

1. **Start the Agents**:
   Ensure you have the agents running locally. From the project root:
   ```bash
   uv run adk web agents --allow_origins='*'
   ```
   This will start the agents on `http://127.0.0.1:8000` (orchestrator) and other ports for specialists.

2. **Configure Environment**:
   Create a `.env` file in the `gradio-ui` directory or ensure the project root `.env` is accessible.
   Required variables for local testing:
   - `AGENT_URL=http://127.0.0.1:8000` (or the URL where the Creative Director is running)

   Required variables for remote (Vertex AI) testing:
   - `GOOGLE_CLOUD_PROJECT=your-project-id`
   - `LOCATION=us-central1`
   - `AGENT_ENGINE_ID=your-agent-engine-id`
   - `GCS_IMAGES_BUCKET=your-images-bucket`

3. **Install Dependencies**:
   From the `gradio-ui` directory:
   ```bash
   uv sync
   ```

4. **Run the Gradio App**:
   ```bash
   uv run python app.py
   ```

## Deployment

To deploy to Cloud Run, use the provided deployment script:
```bash
python deploy/deploy_gradio.py
```
