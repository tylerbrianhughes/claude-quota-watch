# Related projects

Reviewed September 24, 2026. These are independent alternatives, not evidence that anyone copied this project. This comparison is based on their published documentation, not an installation or security audit.

| Project | Documented scope | Relevance |
|---|---|---|
| [clauth](https://github.com/uwuclxdy/clauth) | Account switching, live usage, fallback chains, isolated sessions, MCP delegation and account-change notifications | Broad overlap; automatic rotation alone is not a differentiator |
| [ccswap](https://github.com/errhythm/ccswap) | Claude and Codex usage, configurable automatic thresholds, credential locks, hysteresis and parallel sessions | Thresholds and workload separation already exist |
| [ccswitch](https://github.com/rios0rios0/ccswitch) | Background usage monitor, enrolled backup accounts, configurable automatic rotation | Simpler daemon-oriented alternative |
| [subswapper](https://github.com/lawzava/subswapper) | Separate account homes, quota-aware routing, optional proxy-based live switching | Another approach to preserving running sessions |

This package focuses on an agent-operated recovery contract: authentication, capacity, live adoption, remote access, and goal continuity are separate claims with separate evidence. It preserves genuine drafts, retains unknown standby accounts, deduplicates incidents, and routes a bounded intervention to one owner. We do not claim these ideas are unique across the ecosystem.

A backend integration is a future option. This release does not install these tools, copy their code, manage bearer tokens, or claim to have tested their live behavior.
