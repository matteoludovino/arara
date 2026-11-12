"""
The ledger is the truth; StockLevel and SkuCost are projections of it. These checks prove
the projections agree with it, and that every line's running balance is right. Tests run
them after every stock scenario; `manage.py check_stock` runs them on a live database.
"""

from django.db import connection

LEVEL_VS_LEDGER = """
select l.variant_id, l.location_id, l.quantity, coalesce(sum(m.quantity_delta), 0) as ledger
from stock_stocklevel l
left join stock_stockmovement m on m.variant_id = l.variant_id and m.location_id = l.location_id
group by l.id
having l.quantity <> coalesce(sum(m.quantity_delta), 0)
"""

COST_VS_LEDGER = """
with ledger as (
    select m.variant_id, sum(m.quantity_delta) as quantity, sum(m.value_delta) as value
    from stock_stockmovement m
    join locations_location loc on loc.id = m.location_id
    where loc.kind in ('store', 'warehouse', 'transit')
    group by m.variant_id
)
select c.variant_id, c.quantity, c.value, coalesce(l.quantity, 0), coalesce(l.value, 0)
from stock_skucost c
left join ledger l on l.variant_id = c.variant_id
where c.quantity <> coalesce(l.quantity, 0) or c.value <> coalesce(l.value, 0)
"""

COST_VS_LEVELS = """
select c.variant_id, c.quantity, coalesce(sum(l.quantity), 0)
from stock_skucost c
left join stock_stocklevel l on l.variant_id = c.variant_id
    and l.location_id in (select id from locations_location where kind in ('store', 'warehouse', 'transit'))
group by c.variant_id, c.quantity
having c.quantity <> coalesce(sum(l.quantity), 0)
"""

RUNNING_BALANCE = """
select id, variant_id, location_id, balance_after, running
from (
    select id, variant_id, location_id, balance_after,
           sum(quantity_delta) over (partition by variant_id, location_id order by id) as running
    from stock_stockmovement
) m
where balance_after <> running
"""

CHECKS = {
    "stock level differs from its movements": LEVEL_VS_LEDGER,
    "SKU cost differs from the ledger": COST_VS_LEDGER,
    "SKU cost quantity differs from the inventory levels": COST_VS_LEVELS,
    "movement balance_after differs from the running sum": RUNNING_BALANCE,
}


def stock_problems() -> list[str]:
    problems: list[str] = []
    with connection.cursor() as cursor:
        for label, sql in CHECKS.items():
            cursor.execute(sql)
            problems.extend(f"{label}: {row}" for row in cursor.fetchall())
    return problems
