# Belay concert-ticket app: initial blueprint

**Earlier design:** retain this document for ticketing research. Its
per-purchase approval default and ticket-only initial product framing are
superseded by the [autonomous app architecture](AUTONOMOUS_APP_ARCHITECTURE.md).
The current direction uses advance delegated authority and keeps tickets as
the first demonstration of a system that can support other domains.
Its card/Stripe payment assumptions are also superseded by the selected
[USDC settlement architecture](USDC_SETTLEMENT_ARCHITECTURE.md).

Decisions confirmed by the user: **concert tickets first; United States first**.
Prepared 12 September 2026. This is a proposed product and integration plan,
not a claim that a live ticket or payment connection has been established.

## The product in one sentence

A concert assistant that turns a person's preferences into a suitable ticket
purchase, with clear approval and reliable confirmation of what was bought.

The consumer uses one app. Start with one conversational agent and a small
set of ticketing tools. Build a ticket-specific experience on top of existing
models, ticket providers and payment infrastructure. Belay's recovery work
belongs behind the purchase flow. This consumer product has a different buyer
and distribution strategy from the earlier B2B recovery SDK; keep that choice
explicit when testing demand.

## The experience

Illustrative request, not a live offer: “Find two seats together for this
artist in Chicago next month, under $300 total.”

1. **Understand:** gather the missing artist, city/date flexibility, quantity,
   total budget and seat requirements. Avoid asking again for information
   already supplied. Accessibility needs are explicit constraints.
2. **Find:** retrieve event candidates from a connected source. Display the
   actual date, venue and seller. Event discovery does not establish that
   two adjacent seats are available at a quoted total.
3. **Compare:** explain how each option fits the request. With transactional
   access, obtain the exact seat offer, applicable fees and expiry. If an
   inclusive price is unavailable, do not invent a cheap headline price.
4. **Approve:** show the exact event, seats, quantity, seller, final amount
   and relevant cancellation/transfer conditions before a purchase.
5. **Book:** send the approved request through an authorized checkout route.
   Changed seats or price require a fresh decision; do not silently substitute.
6. **Confirm:** distinguish payment status, merchant order confirmation and
   ticket delivery. A seller link being opened is not purchase evidence.

Do not add hotels or transport to this first version. The architecture can
accept another provider later without exposing a crowd of agents to the user.

## One agent, several tools

```text
User conversation
        |
        v
Concert assistant — understands preferences and explains options
        |
        v
Application controls — validate intent, limits and approval
        |
        +---- Ticket connector ---- Seller inventory / booking system
        |
        +---- Payment connector --- Seller checkout or supported wallet
        |
        +---- Belay recovery ------ Stored intent, provider IDs, outcomes
```

A provider need not operate an AI agent. Its API can return structured event
or order data directly. A connector is our software that translates between
our app's operations and that provider's API. A specialist agent adds model
reasoning and domain instructions around tools; it does not create supplier
access by itself.

Suggested internal tool boundaries, **not existing vendor endpoint names**:

| Tool | Responsibility | Availability in the initial product |
|---|---|---|
| `search_events` | Find event candidates from preferences | First live integration |
| `get_event` | Retrieve date, venue and official purchase link | First live integration |
| `quote_tickets` | Validate exact seats, quantities, total and expiry | Mock first; approved booking integration later |
| `start_checkout` | Open seller checkout or start authorized embedded flow | Seller handoff first |
| `get_order` | Retrieve merchant evidence of the original booking | Requires provider order access |

Use ordinary application code for approval checks, amount comparisons,
state transitions, credential handling and submission. Do not let model
text decide whether an API error means a purchase succeeded. Add specialist
agents only when a separate domain needs independent reasoning and evaluation.
An open marketplace of third-party agents would introduce another product's
onboarding, permissions, quality control, support and economics.

## What the existing infrastructure actually supplies

Ticketmaster's Discovery API offers event discovery and purchase links.
Its transactional Partner API requires an official distribution relationship.
Consequently, a developer key for search does not unlock reservations and
purchases. [Discovery API](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/),
[Partner API](https://developer.ticketmaster.com/products-and-docs/apis/partner/)

Stripe's agent-facing Agentic Commerce Suite is currently described as a
private preview for physical goods. It also requires seller connections;
do not assume it supplies concert-ticket inventory or a ready ticket checkout.
[Stripe's agent integration](https://docs.stripe.com/agentic-commerce/for-agents?agent-checkout-mode=feed-only)

Separately, Link supports US consumers approving payment credentials for
agents. A virtual card and a shared payment token have different merchant
compatibility. The documented spend-request default limits include $500
per request and $500 daily per agent integration; higher limits require
discussion with Stripe. That is a planning constraint, not a scalable ticket
business allowance to assume away. [Link payments](https://docs.stripe.com/agentic-commerce/link-cli/use-link-wallet-pay-online)

This per-request approval requirement describes Link, not every Stripe
product. Stripe also documents Issuing for agents: virtual cards with
spending controls and programmatic authorization, including platform-issued
consumer cards. Platform access requires contacting Stripe and involves a
card program. It is a concrete autonomous-payment path to evaluate, without
assuming it grants ticket-booking access or verifies seat requirements.
[Issuing for agents](https://docs.stripe.com/issuing/agents)

The supplied Stripe interview describes an earlier ACP checkout integration.
Current Stripe documentation also covers UCP, including checkout and order
updates. Both payment and commerce lifecycle standards already exist; our
work would implement them against real providers. Protocol support alone
does not establish inventory access or end-to-end reliability.
[Stripe commerce protocol documentation](https://docs.stripe.com/agentic-commerce/protocol)

Payment credentials fund an accepted checkout; they do not reserve seats,
grant seller automation rights, or prove ticket issuance. Using a browser
to operate an allowed merchant checkout is another integration route, but
adds changing page layouts, login, queues and recovery uncertainty. Use an
approved API where available and a user handoff where needed.

## Two concrete releases

### Protocol choice: evaluate AP2 before a custom signing format

The September 2025 AP2 announcement already includes autonomous concert-ticket
purchasing as an example. Signed agent authorization is therefore an existing
foundation to reuse, not a novel Belay claim.
[Original announcement](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol)

Current AP2 v0.2 uses Checkout and Payment Mandates, each with open and closed
forms. Start with direct user approval of the finalized purchase; consider
advance constrained delegation later. Google announced v0.2 and donation to
the FIDO Alliance on April 28, 2026.
[Current overview](https://ap2-protocol.org/),
[Release announcement](https://blog.google/products-and-platforms/platforms/google-pay/agent-payments-protocol-fido-alliance/)

AP2 defines verification and receipt responsibilities. Its implementation
guidance explicitly assigns duplicate-spend prevention and receipt management
to the shopping agent. Belay could implement these duties and the operator
experience around them. They are not gaps that AP2 overlooks.
[Implementation guidance](https://ap2-protocol.org/ap2/implementation_considerations/)

AP2 leaves catalog and commerce APIs outside its scope. Its dispute-evidence
rules do not specify operational dispute resolution, retention and retrieval.
A ticket-provider agreement and booking integration remain necessary. We have
not verified a compatible AP2 profile spanning Ticketmaster and our chosen
payment provider. The current Belay prototype is not AP2-compliant.

Choose signing algorithms from the adopted profile. In particular, current
AP2 rules exclude deterministic signatures such as Ed25519 for the merchant
Checkout JWT; our earlier generic Ed25519 suggestion is not the default for
that object. This restriction does not apply indiscriminately to every AP2
signature. Pin the specification/schema version before implementation.
[AP2 specification](https://ap2-protocol.org/ap2/specification/)

**Release 1 — find the concert and hand off checkout.**

Build conversation, event results, preference-based comparison and an
official-seller checkout link. Initially connect one discovery source. Store
the search and selected event. Keep a handoff labeled “checkout opened” until
actual confirmation is available; a user-provided receipt should be labeled
as such rather than silently treated as independently verified. No direct
payment integration is required for the seller to take payment on its site.

**Release 2 — complete a purchase inside the experience with one partner.**

First establish access to booking, permitted payment methods, hold expiry,
order retrieval and delivery status. The partner's integration determines
whether Stripe/Link is usable or its own payment route is required. Keep
Stripe test credentials and fictional inventory in a sandbox until that
agreement and technical contract exist.

Extend the existing prototype into a ticket-specific sandbox: quote two
seats; expire the quote; change the price; request approval; lose confirmation
after order creation; then recover or stop. This is the next implementation
scope, not a feature already present in the refund lab.

Acceptance cases for that extension:

- Final total exceeds budget: purchase cannot proceed.
- Seat hold expires or seats change: fetch a new offer and seek approval.
- Merchant creates the order but confirmation is lost: retrieve that order
  before considering another purchase.
- Payment succeeds but tickets remain pending: display those states separately.
- Provider cannot establish order outcome: stop with a visible unresolved case.
- A second click or changed agent response cannot silently authorize a new order.

Belay must persist the purchase identity, approved quote/version, seller,
seat IDs, amount/currency and provider identifiers. Correct provider
idempotency remains part of the solution. The current repository still has
the original research-runtime issues described in REVIEW.md; the refund
demo is not a production ticket SDK.

## United States launch boundaries

Use seller-authorized access and user-controlled checkout. The BOTS Act
restricts circumvention of ticketing controls; a product should not depend
on bypassing queues, ticket limits or anti-bot protections.
[FTC BOTS Act summary](https://www.ftc.gov/legal-library/browse/statutes/better-online-ticket-sales-act)

Design advertised prices to include mandatory fees as required by the FTC's
Fees Rule. Its permitted exclusions do not justify hiding known mandatory
charges behind an “estimated” label. Resolve feed limitations before showing
prices as purchase offers. [FTC pricing guidance](https://www.ftc.gov/business-guidance/resources/rule-unfair-or-deceptive-fees-frequently-asked-questions)

Choose the business role before enabling native sales: referral service,
authorized distributor and ticket reseller can create different obligations.
For example, New York regulates ticket-reseller licensing. Have counsel
assess the actual flow and launch states; seller-hosted checkout is not an
automatic exemption from every obligation. [New York licensing information](https://dos.ny.gov/licensing-ticket-resellers)

Minimize personal information and keep payment credentials out of model
messages and logs. Plan clear customer support ownership and cancellation
information. Add no custodial wallet or resale inventory to the first scope.

## Business proof and cost

“Chat that buys tickets” is a product category, not evidence of originality
or a durable advantage. Test whether users choose this flow over the seller's
own search, whether it helps them find suitable seats, and whether they can
trust the final confirmation. The more difficult assets are authorized
inventory, accurate offers and dependable purchase operations.

Potential revenue includes an agreed referral/distribution commission or a
clearly disclosed service fee. Neither agreement nor willingness to pay has
been established. Track completed purchases where attribution is permitted,
abandonment, time to choose, incorrect offers, unresolved orders and support
cost per booking. One initial catalog is not an internet-wide comparison.

The supplied commerce talks suggest another explicit test: does a
recommendation correspond to an offer the customer can actually buy?
Measure stale or unavailable offers, incorrect seat matches, approval
changes, purchase completion and delivery confirmation. Treat speakers'
adoption forecasts, market figures and preferences about autonomy as claims
to investigate, rather than evidence of demand for Belay. Compare approval
modes using these outcomes instead of assuming greater autonomy is better.

Budget separately for model usage, hosting/state, provider access and
commercial terms, integration maintenance, customer support, legal review
and any payment/dispute costs our chosen role bears. The number of agents
is not a useful proxy for project cost. Obtain the supplier access terms
before estimating a full native-checkout build.

## Additional experiment from the AP2 podcast

The user-supplied episode suggests retaining an unmet request so an
authorized seller can fulfill it later. For example, a user could save
“two adjacent seats with a clear view, under $300 total” until a chosen
deadline. A later qualifying offer would still require purchase approval
in our first implementation. Keeping a search active is separate from
permission to spend.

Test whether this leads to additional suitable purchases and less repeated
searching. A saved search alone does not establish differentiation. Inventory
access, accurate matching, reliable fulfillment and customer acquisition
remain necessary. Keep the user's maximum budget private by default and
avoid treating the maximum as a target price.

This is a proposed experiment, not an implemented service. The accompanying
AP2 podcast learning notes distinguish the episode's architecture and future
vision from verified capabilities. Its demonstrations do not establish fraud
rates, market size or willingness to pay for Belay.
