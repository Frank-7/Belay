# Belay: Stripe, Criteo and a16z commerce learnings

Historical source notes. Stripe is not the selected payment dependency;
the current plan is [USDC settlement on Base](USDC_SETTLEMENT_ARCHITECTURE.md).

Reviewed 12 September 2026. Product scope remains concert tickets in the
United States. This is research and a proposed product direction, not an
announcement of a live integration.

## Sources and review coverage

| Source | Upload date | Material reviewed |
|---|---|---|
| [Implementing the Agentic Commerce Protocol with Stripe — Stripe Developers](https://www.youtube.com/watch?v=l7r9jW2nEOI) | 6 October 2025 | First user-supplied transcript, covering Steve Kaliski's ACP and shared-payment-token demonstration. |
| [Agentic Commerce: What Will & Won't Be — Michael Komasinski, Criteo](https://www.youtube.com/watch?v=KJqLbs-GVXY) | 13 November 2025 | Second user-supplied transcript, covering commerce data, recommendations and the speaker's views on autonomy. |
| [How agentic commerce works (and why it matters) — a16z crypto](https://www.youtube.com/watch?v=F1ICMexazj0) | 27 April 2026 | An accessible third-party transcript, cross-checked against publisher material and current technical documentation. |

Dates are upload dates, not necessarily recording dates. The recordings were
not watched directly. The third video's [transcript source](https://www.usetranscribe.io/yt/F1ICMexazj0/agentic-commerce)
contains transcription errors; avoid verbatim quotes and unverified figures.

## What each source contributes

**Stripe demonstrates an existing payment mechanism.** The interview shows
an agent sharing a seller-scoped payment credential, a seller using it in
a PaymentIntent, and an attempted amount above the permitted limit being
rejected. These are test-code examples in the supplied transcript, not
evidence of a live ticket purchase. The important lesson is that basic
payment scoping already exists. The advertised one-line change concerns
the payment-call parameter; a complete merchant integration still needs
checkout, inventory, approval and order handling.

**Criteo identifies a failure between useful advice and a purchasable offer.**
Komasinski describes researching bicycle tires with an assistant, receiving
broken links or incomplete availability information, and ultimately buying
at a local shop. This is one anecdote, not a measured failure rate. Applied
to Belay, a plausible recommendation must be checked against actual event,
seat, price and availability information before becoming a purchase offer.
We do not need to assume that a vast historical recommendation dataset is
necessary to test this with one provider.

**The a16z discussion separates buying for a person from an agent buying
capabilities for its work.** Buying concert tickets is a consumer purchase;
paying for a venue-data query is a machine-service purchase. Both may appear
in one task, but need distinct budgets, permissions and outcome checks.
The publisher's [headless-merchant article](https://a16zcrypto.com/posts/article/ai-agent-commerce-headless-merchant)
and [Stripe's machine-payment documentation](https://docs.stripe.com/payments/machine)
support the API-service model. They do not establish access to concert seats.

The discussion also raises a different trust question: whose interests does
the agent serve? Our product inference is that Belay should explicitly act
for the buyer. A valid payment credential does not establish that a
recommendation is best for that buyer. If paid placement is introduced,
make it visible and preserve the user's requirements.

## What is documented at Stripe now

- **Shared payment tokens:** seller, currency, maximum amount and expiry can
  constrain a payment credential. They do not encode all ticket preferences.
  Additional customer authentication can be required. [Current SPT guide](https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens?agent-seller=agent)
- **Link:** its spend-request flow asks the customer to approve an individual
  request before releasing a payment credential. [Link guide](https://docs.stripe.com/agentic-commerce/link-cli/use-link-wallet-pay-online)
- **Issuing for agents:** autonomous virtual-card purchases, spending
  controls and programmatic authorization are documented, including
  platform consumer cards. Platform access requires contacting Stripe.
  This is a card-program integration. [Issuing for agents](https://docs.stripe.com/issuing/agents)
- **Commerce protocols:** the interview describes ACP. Stripe's current
  protocol page covers UCP checkout and order updates. Do not treat all
  code or product availability in the recording as current, or infer that
  a protocol's existence supplies ticket inventory. [Current protocol page](https://docs.stripe.com/agentic-commerce/protocol)

## What this changes for Belay

Keep the working problem concrete: **help a buyer's agent obtain suitable
tickets and establish what actually happened to the purchase.** Payment
permissions, spending limits, transaction records and safe payment retries
already have existing infrastructure. Belay must demonstrate useful work
across the ticket purchase rather than claim to invent these foundations.

Keep final purchase approval as the first release. Investigate advance
permission for users who cannot attend to a time-sensitive purchase, with
precise requirements and compatible providers. Criteo's skepticism about
autonomy is a viewpoint to test; it is not evidence that every autonomous
purchase is unwanted. Likewise, the a16z discussion does not establish
that fully autonomous shopping is already a successful mass-market product.

The next ticket sandbox should expose these distinct outcomes:

| Situation | Required behavior |
|---|---|
| Payment is within budget, but the event or seats are wrong. | Reject the offer based on ticket data. A valid payment limit is insufficient. |
| Correct seats were shown, but the quote or hold has expired. | Refresh availability and approval as required; do not silently substitute. |
| The order may have been created, but confirmation was lost. | Reconcile the existing purchase before considering another. |
| Payment is confirmed but ticket delivery is pending. | Display the two states separately. |

Measure offer accuracy, changes users make before approval, losses caused
by approval delay, completed suitable purchases and unresolved orders.
For a merchant partner, test additional completed sales; for a buyer, test
reduced effort and correct outcomes. These are proposed measurements.

The supplied Criteo percentages, catalog size and growth figures have not
been independently established here. Forecasts about a dominant shopping
platform or advertising's future are competing commercial theses. None of
these sources establishes Belay's market size, willingness to pay or durable
advantage. The existing prototype remains a refund-recovery simulation;
the ticket scenarios above are not implemented by this research update.
