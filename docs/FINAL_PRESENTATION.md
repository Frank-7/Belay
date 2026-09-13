# AI Apps final presentation

**Position:** Belay helps an operator determine what an interrupted AI action
actually did, and what can safely happen next.

Use the local Recovery Desk as the main demonstration. Keep a labeled recording
as a fallback. A GitHub Pages recording is not a live Python backend.
The team is staying in AI Apps; the application story does not depend on
another track move.

## 60-second script

**0–10 seconds — problem**

> Your AI agent sends a refund. The confirmation disappears. A support operator
> now has to answer a costly question: did the payment happen, or should we try again?

**10–20 seconds — application**

> Belay turns that uncertainty into an investigation. Here is the original
> request, the available evidence and the decision the operator needs to make.

**20–40 seconds — demonstrate**

> This report says nothing happened, but this receipt says it did. Belay blocks
> the unsupported conclusion and asks for a consistent source. After we refresh
> the evidence, it records the original outcome without sending another refund.

Use the conflicting-source simulation for that script. If showing the wallet
path instead, replace the demonstration beat with:

> I signed this small test-USDC transfer in MetaMask. Belay checks the original
> transaction against the network, token, recipient and amount, then records
> its finalized receipt. It does not send another transfer.

**40–50 seconds — AI and evidence**

> The optional AI assistant selects evidence and proposes an explanation.
> Deterministic checks decide whether that evidence supports the conclusion.
> The original request and current permission remain the authority.

Name the actual selected mode. If the demonstration uses the deterministic
baseline, say so and describe the AI adapter as available, not observed live.

**50–60 seconds — impact and limit**

> We are starting with teams whose agents issue refunds. The goal is less
> investigation time without unsupported resolutions. This is a local,
> test-only demonstration; our next proof is a measured pilot on real incidents.

## One number, with its denominator

Choose one result supported by the exact artifact you show:

| Result | Honest interpretation |
|---|---|
| 8 resolved, 14 abstained, 2 refused out of 24 | Current portable heuristic evaluation on constructed post-crash states; zero false resolutions in that run. |
| 12 expected outcomes out of 12 | Frozen constructed boundary suite: 2 committed, 2 absent, 8 abstentions. Subsequent runs are regressions, not new holdouts. |
| 0 violations out of 240 anchored trials | Historical committed SIGKILL result under the research contract and grader's limits; 960 kills across all four runtimes. |

Do not combine those denominators or claim a 100% production recovery rate.
The 24-case outcome is one-third useful resolution coverage, with safe unknowns
and permission refusals reported separately. Display the report's fixture hash,
configuration and revision when possible.

## Judge questions

**Why is this an AI application?**

The operator investigates evidence and receives a proposed explanation of a
constrained real-world action. The optional model selects and interprets
records; it does not invent authority. On today's small structured cases the
heuristic already works. We have not established that the model improves
accuracy or time. The next comparison must test that increment on messier,
independently labeled evidence.

**Why not just use Temporal or a stable idempotency key?**

Use them. Correct durable workflows and stable keys already handle many
failures, and can include fresh permission/business-condition checks. Belay
focuses on the operator's uncertain-outcome investigation, explicit evidence
coverage and refusal when an answer is unsupported. Our comparison should
include the correctly guarded existing implementation.

**What happens when two sources disagree?**

The validator abstains, exposes the conflict and identifies the evidence
needed next. A bounded scan prevents the model from hiding a conflicting
available source by citing only the convenient one. This does not prove which
source is true or make untrusted local files authoritative.

**Who holds the funds? Can the agent spend them?**

For the test-network demonstration, the person controls their MetaMask key
and signs the transfer. Belay has no custody, private key or signing service.
The server's adapter only reads evidence. A missing receipt cannot authorize
a second transfer.

**Does blockchain make the action reversible or guarantee a refund?**

No. The test chain provides transaction evidence under its network and RPC
assumptions. It does not reverse a completed transfer, fund compensation or
establish the user's business entitlement. Belay offers no financial guarantee.

**Did you show that live models frequently change their decisions?**

No. The completed historical 50-response cells showed no within-cell decision
disagreement. They do not establish determinism, and different configurations
must not be pooled into an incident rate. The failure experiment tests a
mechanism; the frequency remains a separate empirical question.

**Why would anyone buy this?**

Our buyer hypothesis is a team already allowing agents to issue consequential
actions. They may pay if Belay cuts investigation time and unsupported
resolutions beyond their existing workflow. We have not yet measured that
demand; a shadow pilot must establish the value.

**Is this production ready?**

It is a local application and test-network demonstration. The remaining work
includes real incident evaluation, authenticated deployment, provider-specific
authority/finality contracts, concurrency and deployment migration rules.
The two original journal/anchor defects were fixed in PR #7; those fixes do
not eliminate the remaining scope limits.

## Three buyer questions

1. Describe the most recent automated action whose outcome your team could not
   establish immediately. What records did you inspect, how long did it take,
   and what was the impact?
2. What do your current idempotency, workflow and approval controls already
   handle well? Where does an operator still need to investigate?
3. What evidence would you require before authorizing another action or
   accepting the original as complete, and what would make a shadow pilot
   worth your team's time?

Record the actual answers and permission to quote them. These are prepared
questions; no customer interview or outreach is asserted.

## Final rehearsal and external dependencies

Confirm the earlier remaining checkpoint times in [CHECKPOINTS.md](CHECKPOINTS.md).
Open the exact branch revision, create a fresh incident, verify the audio and
record the whole journey before trimming it. Keep the original evidence receipt
and report separate from the video.

A live OpenAI run needs explicitly configured credentials, model and quota.
A real test-network run needs faucet tokens, a compatible browser wallet and a
person's signature. Do not substitute a mock and label it live. No real-money
purchase is needed to demonstrate either path. If either dependency is
unavailable, use the working offline path and state the remaining limitation.