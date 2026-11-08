Read the current file every time you are prompted to be up to date. 
Keep this project as simple as possible - the goal is NOT to be production ready, but to teach me how this works and how to get to production level code.

## End goal

The end goal is to beat the market: generate a good risk-adjusted return after fees and slippage, not just to learn. Judge every strategy and feature by whether it plausibly adds real, after-cost return versus buy-and-hold (SPY for stocks, BTC for crypto). "Simple" and "teach me" describe how to build it, not a reason to skip checking whether it makes money.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. Route only to skills in the session's available-skills list; answer directly for quick questions or small scoped edits.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate, unless one read-only check confirms the cause and a narrow fix (then fix it and run the focused test)
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
