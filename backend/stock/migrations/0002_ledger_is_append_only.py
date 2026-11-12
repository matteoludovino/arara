from django.db import migrations

FORWARD = """
create function stock_ledger_append_only() returns trigger language plpgsql as $$
begin
    raise exception 'stock ledger is append-only: % on % is not allowed', tg_op, tg_table_name
        using errcode = 'restrict_violation',
              hint = 'Correct stock with a new entry (an adjustment or a reversal), never by editing history.';
end;
$$;

create trigger stock_entry_append_only
    before update or delete on stock_stockentry
    for each row execute function stock_ledger_append_only();

create trigger stock_movement_append_only
    before update or delete on stock_stockmovement
    for each row execute function stock_ledger_append_only();
"""

BACKWARD = """
drop trigger stock_movement_append_only on stock_stockmovement;
drop trigger stock_entry_append_only on stock_stockentry;
drop function stock_ledger_append_only();
"""


class Migration(migrations.Migration):
    """Immutability enforced by PostgreSQL, whatever path a write takes (ORM, admin, raw SQL)."""

    dependencies = [("stock", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
