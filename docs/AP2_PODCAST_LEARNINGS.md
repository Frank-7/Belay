# Belay: lessons from the AP2 podcast

Recorded 12 September 2026. These notes supplement the concert-app blueprint.
Scope remains concert tickets in the United States.

## What the supplied material establishes

The three attachments contain one summary and two byte-identical copies of
one Agent Factory transcript. They are one underlying source, not three
independent confirmations. The transcript contains transcription errors and
launch-era terminology; its publication date was not supplied.

The episode explains an architecture, shows a demonstration and proposes
future commerce scenarios. Its wrong-ticket examples are illustrative. It
does not establish actual fraud losses, customer demand for Belay, market
size or willingness to pay.

## Lessons to carry into the product

| Lesson | Decision for our concert assistant |
|---|---|
| A request must become a precise agreement. | Turn “two good tickets under $300” into an event, city/date, quantity, adjacent-seat requirement, view restrictions and total budget. Clarify whether a price limit is per ticket or for the whole purchase. Unknown seat information stays unknown. |
| The user needs to understand what they approve. | Show the exact seller, event, seats, quantity, total and relevant terms in a structured approval screen. Changed purchase details need a fresh decision in the first version. |
| Different jobs need different controls. | Let the conversational agent find and explain options. Use ordinary application code for limits, approval validation and order tracking. Use an authorized ticket provider and its supported payment route. Each role does not require another LLM. |
| Permission and outcome are different facts. | Record what was approved, what the provider accepted and whether tickets were delivered. A payment response alone cannot justify telling the user that tickets are ready. |
| An unsuccessful search can still express valuable demand. | Explore a saved request that can receive a matching offer later. Require user consent to keep it active, specify an expiry and offer an easy cancellation control. Saving a search does not authorize a purchase. |
| The value must appear in completed customer outcomes. | Test whether this helps people obtain suitable tickets with less effort, and whether an authorized seller receives additional completed sales. Protocol adoption alone is not proof of either. |

## The most useful new business hypothesis

The episode's unavailable-red-dress example suggests a useful experiment:
retain a specific unmet request instead of losing it when the first search
fails. Applied to Belay:

1. A user wants two adjacent seats for a particular concert, with a clear
   view, for no more than $300 total.
2. No connected seller currently has a matching offer. Belay explains this
   and lets the user save the request until a chosen deadline.
3. An authorized provider later exposes a qualifying offer for $270 total.
4. Belay checks the current details and asks the user to approve it.
5. The provider completes checkout; Belay reports the actual order and
   delivery state available from that integration.

This is a proposed product experiment, not an implemented monitoring service
or a real ticket offer. Start with explicit approval of each purchase.
Autonomous buying would need a separately implemented and verified delegation
flow.

A saved search alone is not a durable advantage. Potential value would come
from access to useful inventory, accurate matching, dependable purchase
completion and distribution. We still need to establish those capabilities
and customer demand. Treat the maximum budget as a spending ceiling; do not
automatically reveal it to sellers or optimize toward the maximum price.

## Corrections to retain alongside the transcript

| Episode claim or impression | More accurate interpretation |
|---|---|
| Cart and intent mandates are the current implementation model. | Current AP2 v0.2 uses Checkout and Payment Mandates, with open constraints and closed purchases. It also includes a non-agentic Trusted Surface and requires deterministic validation. Pin the adopted version before implementation. [AP2 specification](https://ap2-protocol.org/ap2/specification/) |
| Avoiding card numbers means no PCI obligations. | Keeping card data out of the agent reduces exposure; actual scope depends on its role and integration. Even fully outsourced payment processing does not automatically remove a merchant's responsibilities. This does not imply every shopping agent is a merchant. [PCI SSC](https://www.pcisecuritystandards.org/faqs/does-pci-dss-apply-to-merchants-who-outsource-all-payment-processing-operations-and-never-store-process-or-transmit-cardholder-data/), [Stripe security guide](https://docs.stripe.com/security/guide) |
| A biometric signature makes data encrypted and unchangeable. | Signing and encryption serve different purposes. In FIDO, local biometric verification can authorize use of a cryptographic key; biometric data stays on the device. Describe signed records as tamper-evident. [FIDO specifications](https://fidoalliance.org/specifications/) |
| Signed approval settles responsibility with “no takebacks.” | Signed records provide evidence. They do not alone determine liability, establish delivery or erase applicable customer rights. AP2 leaves operational dispute resolution outside its scope. [AP2 dispute evidence](https://ap2-protocol.org/ap2/specification/#dispute-evidence) |
| The PayPal-labelled demonstration proves an available live integration. | The official AP2 samples use mocked payment providers. The supplied recording does not independently establish real money movement or production access. [AP2 FAQ](https://ap2-protocol.org/faq/) |
| Trust registries provide access to millions of merchants now. | The transcript gives this as a hypothetical future example. It is not evidence that Belay can access those merchants, their inventory or checkout. |

## How this affects Belay's technical scope

AP2 supplies a standard for transaction authorization and evidence; it does
not supply catalog APIs or ticket inventory. Use it where the participating
providers support the relevant flow. [AP2 specification](https://ap2-protocol.org/ap2/specification/)

AP2 already assigns double-spend prevention, receipt management and error
handling to shopping-agent implementations. Belay's execution work could
implement these responsibilities. We should not describe them as problems
the protocol ignores. [AP2 implementation guidance](https://ap2-protocol.org/ap2/implementation_considerations/)

For the next ticket sandbox, test an ambiguous budget, an unavailable match,
a changed quote, an expired hold and a lost order confirmation. A saved
request must not trigger an unapproved purchase. An uncertain provider
outcome must remain visibly unresolved until evidence arrives.

The first live release remains discovery plus seller checkout. Native
booking depends on authorized transactional access. The existing refund
recovery prototype remains a separate simulation; these notes add no live
ticket, wallet or AP2 connection.
