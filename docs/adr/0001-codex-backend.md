# Use an installed Codex backend

V1 supervises the official Codex CLI to use Keith's ChatGPT subscription, instead of implementing the originally proposed independent HTTP agent loop. This trades a standalone runtime and direct tool control for an external dependency with established subscription authentication; Zig learning focuses on process lifecycle, streaming protocols, and a reliable CLI contract.
