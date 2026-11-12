from django.db import connection

CREDIT_VS_LEDGER = """
select c.code, c.balance, coalesce(sum(e.amount), 0)
from pos_storecredit c
left join pos_storecreditentry e on e.credit_id = c.id
group by c.id
having c.balance <> coalesce(sum(e.amount), 0)
"""

RETURNED_VS_LINES = """
select i.id, i.quantity_returned, coalesce(sum(r.quantity), 0)
from pos_saleitem i
left join pos_returnline r on r.sale_item_id = i.id
group by i.id
having i.quantity_returned <> coalesce(sum(r.quantity), 0)
"""


def pos_problems() -> list[str]:
    problems: list[str] = []
    with connection.cursor() as cursor:
        for label, sql in (
            ("store credit balance differs from its entries", CREDIT_VS_LEDGER),
            ("returned quantity differs from return lines", RETURNED_VS_LINES),
        ):
            cursor.execute(sql)
            problems.extend(f"{label}: {row}" for row in cursor.fetchall())
    return problems
