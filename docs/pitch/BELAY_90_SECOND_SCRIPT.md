# Belay 90-second investor pitch

## Recording plan

| Time | Screen | Speaker |
|---|---|---|
| 0:00–0:13 | Slide 1 | Abdulaziz |
| 0:13–0:32 | Slide 2 | Amir Khan |
| 0:32–1:03 | Live Belay demo, then Slide 3 if a static fallback is needed | Abdulaziz |
| 1:03–1:27 | Slide 4 | Amir Khan |
| 1:27–1:30 | Slide 5, blank | Silence |

## Exact script

### 0:00–0:13 — Abdulaziz

> AI agents can shop and call payment APIs. The unsolved step is control: did the agent follow the user’s exact instruction, and what happened when the payment result became unclear? Belay is that control layer.

### 0:13–0:32 — Amir Khan

> Three failures create losses: the AI misreads the payee or amount, broad permission becomes an unintended payment, and a timeout triggers a duplicate retry. This matters across 8.1 billion U.S. B2B ACH payments in 2025. Rails prove money moved, but not that the agent followed the instruction.

### 0:32–1:03 — Abdulaziz, live demo

> Here is the simulator. I ask Belay to pay invoice INV-1042 for $1,250. It builds an editable plan and leaves unknown fields blank. I approve the recipient, amount, reference, and limit. Deterministic checks enforce one operation ID, simulate USDC settlement with USD delivery, and link instruction, approval, and result in one receipt. If a response is lost, Belay checks that operation before any retry.

Demo actions:

1. Select the invoice example or enter `Pay invoice INV-1042 for $1,250 to Acme Design by September 30`.
2. Select **Build my payment plan**.
3. Point to the editable payee, amount, maximum, invoice reference, and the two synchronized views.
4. Select **Authorize & pay now**.
5. Point to **15 of 15 passed**, **one operation**, **attempts: 1**, and the linked receipt.

### 1:03–1:27 — Amir Khan

> We sell to AI platforms, fintech teams, and financial institutions through subscription and fixed operation fees, with no Belay percentage take rate. Stripe, Google AP2, and payment networks are opening the rails. Belay controls execution and recovery. We are raising $1.5 million for regulated integrations, independent security review, and three design-partner pilots.

### 1:27–1:30 — silence

Show the blank navy slide. Do not speak.

## Claims to keep precise

- Say **working end-to-end simulator**, not production payment system.
- Say **designed to reduce agent errors and duplicate execution**, not fraud-proof.
- Say **simulated USDC settlement with USD delivery**. The MVP moves no live funds.
- Say **no Belay percentage take rate**. Network, gas, foreign-exchange, conversion, and payout costs still exist and would pass through.
- Say **Google AP2 provides mandate language; payment providers provide credentials and rails; Belay controls execution and recovery**.
- Treat the $2,000 monthly fee, $0.25 operation fee, 85% gross-margin goal, and customer counts as illustrative targets.

## Sources behind the slides

- Nacha, 2025 ACH Network volume and value: https://www.nacha.org/content/ach-network-volume-and-value-statistics
- U.S. Census Bureau, Q2 2026 retail e-commerce: https://www.census.gov/retail/ecommerce.html
- Google Cloud, Agent Payments Protocol: https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol
- Stripe Agentic Commerce: https://docs.stripe.com/agentic-commerce
- Visa Intelligent Commerce: https://usa.visa.com/about-visa/newsroom/press-releases.releaseId.22276.html
- Mastercard Agent Pay: https://newsroom.mastercard.com/news/press/2025/april/mastercard-unveils-agent-pay-pioneering-agentic-payments-technology-to-power-commerce-in-the-age-of-ai/
- University of Connecticut: https://uconn.edu/about-us/
