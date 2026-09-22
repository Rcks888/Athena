# SUPERSEDED — these results contain an unmodelled funding constraint

**Do not quote any figure in this directory.** Superseded 2026-09-22 by the
cash-gated re-run in `results/v6_runA2_*`.

## What is wrong with them

These runs reproduced live Ares faithfully, including the fact that **live tracks no
cash balance and performs no funding check anywhere**. That reproduced live's
*missing check*, which produced a portfolio that could not have existed:

| | days with negative cash | worst overdraft |
|---|---|---|
| Universe A (130) | 39 of 1241 (3.1%) | −$105.15 |
| **Universe B (98)** | **309 of 1241 (24.9%)** | **−$356.00** |

Universe A additionally spent 242 days with `0 <= cash < $149`, where a slot existed
but could not be funded at the full static stake.

Live Ares trades through IBKR, and **IBKR enforces the constraint live's code
omits** — those orders would have been rejected. The broker is part of the live
system, so modelling its funding rule completes the model rather than editing the
strategy. This is categorically unlike the inert `RSI`/`EMA_20` queue gates, which
no external party enforces and which remain reproduced as-is.

## The specific figures that must not be reused

- **Universe B: −43.89% / $561.07 / PF 0.702** — invalid. A quarter of the run was
  financed by an overdraft that does not exist.
- **Universe A: −8.46% / $915.35 / PF 0.922** — only mildly affected and
  directionally defensible, but superseded too, since it was produced by the same
  unconstrained engine.

## Why this was not caught

`run_sim` asserted `cash >= 0` on the **terminal day only**, so a 309-day overdraft
that had recovered by the final bar never tripped it. The assertion's comment — "at
5 slots x $149 it cannot overdraw" — was false: the stake is constant while equity
falls, so 5 × $149 eventually exceeds the account. Solvency is now asserted on every
day of the simulation.

The direction of the correction was not predictable in advance. Refusing entries
removes winners and losers alike.
