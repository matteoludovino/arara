from django.db import connection

# What sits in the transit location must be exactly what open transfers have on the road.
TRANSIT_VS_TRANSFERS = """
with on_the_road as (
    select l.variant_id, sum(l.quantity_sent) as quantity
    from transfers_transferline l
    join transfers_transfer t on t.id = l.transfer_id
    where t.status = 'in_transit'
    group by l.variant_id
), in_transit as (
    select s.variant_id, s.quantity
    from stock_stocklevel s
    join locations_location loc on loc.id = s.location_id
    where loc.kind = 'transit' and s.quantity <> 0
)
select coalesce(r.variant_id, t.variant_id), coalesce(r.quantity, 0), coalesce(t.quantity, 0)
from on_the_road r
full join in_transit t on t.variant_id = r.variant_id
where coalesce(r.quantity, 0) <> coalesce(t.quantity, 0)
"""


def transit_problems() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(TRANSIT_VS_TRANSFERS)
        return [f"transit stock differs from open transfers: {row}" for row in cursor.fetchall()]
