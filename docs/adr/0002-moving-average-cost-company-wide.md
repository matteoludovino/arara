# ADR 0002: Moving average cost, company-wide

**Status:** accepted · **Date:** 2026-11-01

## Context
Margin and stock value need a cost per piece. Clothing is bought in batches at prices that drift; pieces move between stores after they are bought.

## Decision
- **Weighted moving average per SKU, across the whole company**, kept as one lockable row (`SkuCost`: quantity and value; cost = value ÷ quantity, four decimals).
- A transfer between inventory locations moves pieces, never value: the average doesn't change. When the company's quantity of a SKU reaches zero, the last piece out takes whatever value is left, so no cents are stranded.
- Documents freeze what things were worth: a sale line keeps its cost (CMV), so a return re-enters inventory at exactly the cost it left with, and last month's margin never changes.
- A store's stock value at a moment = its pieces × the company average of that SKU at that moment; summed over locations it equals the ledger total.

## Consequences
- One average is simple to explain to a store owner and needs no lot tracking.
- **Fiscally, Brazilian cost is per establishment (each CNPJ).** A company with stores under different CNPJs would need the average per CNPJ: the `SkuCost` key would become SKU × establishment, and transfers between establishments would carry value. The ledger already records every movement with its value, so that is a projection change, not a data loss.
