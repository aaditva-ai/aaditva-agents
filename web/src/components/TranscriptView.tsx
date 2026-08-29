import type { Transcript } from "../api/selectTranscript";
import { StepCard } from "./StepCard";
import { StatusBanner } from "./StatusBanner";

/**
 * On mount with no cache, useCampaignEvents simply refetches from the
 * first cursor (no `since`), so this component needs no special-case
 * rehydration logic for a mid-campaign reload -- the same render path
 * handles fresh load, reload, and live update (plan Step 5).
 */
export function TranscriptView({
  transcript,
  onResume,
  isResuming,
}: {
  transcript: Transcript;
  onResume?: () => void;
  isResuming?: boolean;
}) {
  return (
    <div className="transcript">
      <StatusBanner status={transcript.status} onResume={onResume} isResuming={isResuming} />
      {transcript.groups.map((group) => (
        <StepCard key={group.key} group={group} />
      ))}
    </div>
  );
}
