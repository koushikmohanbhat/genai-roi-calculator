# Using it with a customer

A suggested path for a partner, from first meeting to an approved business case.

1. **First meeting: the web page.** Pick the closest example and change the drivers with the customer in the room:
   volume, handling time, loaded cost, the share they would send to an agent. It takes ten minutes and gives a range,
   not a commitment. Say the numbers are indicative.
2. **Baseline from their data.** Ask for a month of volume and handling time from their ticketing or case system, their
   loaded cost per hour (finance has it; salary alone understates it), and today's error or rework rate. Put the
   source of each in `assumptions`.
3. **Measure, don't guess.** Run the pilot through the eval framework (4.1) on their own cases and import the results
   (`roi import-evals`). Containment and tokens per task now come from their data. Use `--conservative` for the version
   that goes to finance.
4. **Compare the routes to market.** Add options for the same model on the OpenAI API and on Bedrock (route, tier,
   AgentCore platform costs), and a routed design if a small model handles most tasks. Put negotiated rates in
   `price_overrides`.
5. **The business case.** `roi run` and send the workbook and the HTML report. Walk through the tornado: the top two or
   three drivers are where the customer should challenge the inputs. Break-even containment is the number to hold the
   pilot to.
6. **After go-live, close the loop.** Re-run with production volumes and the online 4.1 results. A business case that
   is checked against what happened is the one that gets the next workload funded.

## What not to claim

- **Containment from an eval is not production containment.** Say which it is; the reports do.
- **Labour savings are not cash savings** unless the customer will redeploy, not backfill, or stop an outsourcing
  contract. That's `benefit_realisation`; agree it with their finance team, and show the case at 50% as well.
- **Prices change.** Date them on every slide and refresh the catalog (`roi prices --check`).
- **Cheapest isn't best.** An option goes to the customer only if it passed the quality and safety gates.
- The examples are illustrative, not benchmarks.
