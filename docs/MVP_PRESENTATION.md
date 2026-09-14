# Belay: plain-language MVP presentation

Presentation script for the proposed v0.3 architecture. All example purchases,
provider replies, coverage and money are fictional. This is not a live bank,
merchant, blockchain or insurance demonstration.

## The one-sentence explanation

Belay lets an agent buy within your rules, pays suppliers in dollars using
USDC underneath, and provides an evidence-based path to recover from eligible
purchase failures.

## Six scenes

### 1. Give the assistant a job

User: "Buy two adjacent concert tickets. Spend no more than $300 in total."

Belay: "Exactly two, for this event and date. I will use an allowed seller
and stay inside your limit. Here are the protection terms for this mission."

Explain: The model understands the request. Ordinary code checks the rules.
The user initially approves the mission and funds its budget.

### 2. Pay a normal supplier

Belay finds two tickets at $100 each. The supplier wants dollars, not crypto.

Explain: Belay sends the approved USDC amount to an approved payment partner.
The partner converts it and sends $200 to the supplier's bank against the
order. The supplier does not need a crypto wallet. The demo assumes zero fees
and a 1:1 conversion; a live transaction uses an actual quote.

### 3. Keep a useful receipt

The receipt has four sections: your instruction, what was ordered, where the
payment went, and what was delivered. Two tickets delivered correctly closes
the task. Payment success alone does not prove delivery.

### 4. Show a supplier failure

The supplier has received $200 but has not supplied the tickets. A clearly
eligible claim is approved under the demo terms.

Explain: Belay's separate reserve pays the user 200 USDC. The user can withdraw
it or authorize a different purchase. Belay handles recovery separately. The
supplier still has the original $200 until recovery succeeds; no transaction
has been magically reversed.

### 5. Show an agent mistake

First, make the model propose three tickets: the checker blocks it.
Then load a separately labeled historical fault: the system bought three
$100 tickets even though the user authorized two.

Explain: This fault should have been prevented. The two wanted tickets remain
valid. A covered agent-error claim reimburses the extra $100, less any refund
already received. The same loss cannot be claimed twice.

### 6. Show the difficult case honestly

A user reports a damaged or incorrect product, but the evidence conflicts.

Explain: Belay collects evidence and sends the case for review. AI can summarize
the facts; it cannot turn an uncertain photo into unquestionable truth. The
case shows its status, reviewer and next step instead of pretending it is done.

## A roughly 60-second pitch

"An agent can choose an item and pay for it. The hard part is knowing it bought
the right thing, paying a supplier that wants ordinary dollars, and helping
the customer when the result is wrong.

Belay connects those steps. You approve a task and spending rules. The agent
finds an offer, but deterministic checks control the actual purchase. USDC
moves through our payment system; an approved partner pays the supplier in USD.

Our receipt connects what you requested, what was bought, what was paid and
what was delivered. If funds are still held, we can return them under the
rules. If the supplier has already been paid, an eligible prompt reimbursement
comes from a separate funded reserve, while recovery continues.

We start with one ticket-purchase workflow. This presentation uses simulated
payments and protection. The MVP will test exact-order execution, USD payout
recovery and the cost of providing useful customer remedies."

## Questions judges are likely to ask

| Question | Clear answer |
|---|---|
| Does the seller accept crypto? | No. The main design pays USD through an approved provider, using a payment method the seller accepts. |
| Can it pay every website? | Not initially. The MVP uses one invoice/bank-payment supplier. Card-only sellers need a later issuing adapter. |
| Where does a reimbursement come from? | Held customer funds if still available; otherwise separate protection capital or an actual partner obligation. |
| Who decides a product was wrong? | Narrow evidence rules for clear cases; a separate reviewer for disputed or uncertain cases. |
| Why blockchain? | USDC funding, explicit on-chain permissions and inspectable settlement. It does not make banks or delivery part of one atomic transaction. |
| Why not use an existing payment company? | We intend to integrate one. Belay's work is the agent control, linked evidence, workflow recovery and protection operation. |
| Are you insured? | No partner or live coverage is established. The proposed agent-error guarantee needs defined funding and terms. |
| Does your AI run inside the demo? | The presentation dialogue was authored with the assistant. Recorded fixture mode is labeled; a live model endpoint is a later explicit integration. |
| What has actually been built? | Existing local purchase/recovery simulators and this architecture. The new USD payout, contract and reserve workflow remain to be implemented. |

## Words to use carefully

Say "eligible reimbursement", "provider payout pending", "funded reserve",
"verified order" and "proposed integration" when those are the actual facts.
Do not say "unlimited refunds", "fraud-proof", "instant dollars everywhere",
"blockchain reverses any payment", "insured" or "works with every merchant".

The full technical and commercial outline is [MVP_MASTER_PLAN.md](MVP_MASTER_PLAN.md).
