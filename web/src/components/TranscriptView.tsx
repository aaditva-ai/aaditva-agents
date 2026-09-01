import { useState } from "react";
import type { Transcript } from "../api/selectTranscript";
import { useCampaignEvaluation, useTriggerJudgeEval } from "../api/queries";
import { StepCard } from "./StepCard";
import { StatusBanner } from "./StatusBanner";
import { JudgeScorecard } from "./evals/JudgeScorecard";

/**
 * On mount with no cache, useCampaignEvents simply refetches from the
 * first cursor (no `since`), so this component needs no special-case
 * rehydration logic for a mid-campaign reload -- the same render path
 * handles fresh load, reload, and live update (plan Step 5).
 */
export function TranscriptView({
  transcript,
  sessionId,
  onResume,
  isResuming,
}: {
  transcript: Transcript;
  sessionId?: string;
  onResume?: () => void;
  isResuming?: boolean;
}) {
  const [showScorecard, setShowScorecard] = useState(false);
  const { data: evalData } = useCampaignEvaluation(sessionId);
  const triggerJudge = useTriggerJudgeEval();

  const handleEvaluateClick = async () => {
    setShowScorecard(true);
    if (!evalData?.evaluated && !triggerJudge.isPending && sessionId) {
      try {
        await triggerJudge.mutateAsync({ sessionId, force: false });
      } catch (err) {
        console.error("Evaluation trigger failed:", err);
      }
    }
  };

  return (
    <div className="flex flex-col gap-4 w-full pb-8">
      <StatusBanner
        status={transcript.status}
        onResume={onResume}
        isResuming={isResuming}
        onEvaluate={sessionId ? handleEvaluateClick : undefined}
        isEvaluating={triggerJudge.isPending}
        hasEvaluation={Boolean(evalData && evalData.evaluated !== false)}
      />

      {showScorecard && sessionId && (
        <div className="animate-fadeIn">
          <JudgeScorecard
            sessionId={sessionId}
            onClose={() => setShowScorecard(false)}
          />
        </div>
      )}

      {transcript.groups.map((group) => (
        <StepCard key={group.key} group={group} />
      ))}
    </div>
  );
}
