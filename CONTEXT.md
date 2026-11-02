# zigagent

Terms for the Codex-backed command-line supervisor.

## Language

**Run**: One independent request supervised by zigagent, ending in one result; it may include a caller check after the agent finishes.
_Avoid_: Session, conversation, job

**Backend**: The installed Codex CLI that owns authentication, model requests, the agent loop, and tools.
_Avoid_: Provider, embedded model

**Workspace**: The run's working directory, not a security boundary.
_Avoid_: Sandbox, jail

**Caller check**: The explicit command the caller supplies to verify a completed agent result; distinct from tests the agent chooses to run.
_Avoid_: Agent verdict, self-verification

**Result**: The versioned final envelope emitted by zigagent, with separate run and verification statuses.
_Avoid_: Transcript, raw event stream

**Execution deadline**: The finite deadline shared by backend execution and the caller check, beginning after authentication succeeds.
_Avoid_: Model timeout, per-tool timeout
