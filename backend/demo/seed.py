"""
A fictional two-store clothing shop with a few weeks of history, written through the same
services the API uses: every sale, receipt, transfer and count goes through the ledger, the
locks and the checks, so the demo data is as consistent as real data.

History needs past dates, and the ledger is append-only (no backdating with UPDATE), so the
seed lives through those weeks on a simulated clock: `timezone.now` returns the clock's time.
Randomness comes from a fixed seed: every run tells the same story.
"""

import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import F, Sum
from django.utils import timezone

from accounts.models import Approval, Role, User
from accounts.services import grant_approval
from catalog import services as catalog
from catalog.models import Brand, Category, Collection, Color, Product, ProductVariant, Size, SizeGrid
from common.cnpj import with_check_digits as cnpj
from counts import services as counts
from locations.models import Location
from pos import services as pos
from pos.models import CashMovement, CashRegister, CashSession, Payment, Sale, SaleReturn
from purchasing import services as purchasing
from purchasing.models import PurchaseOrder, Supplier
from stock.models import StockLevel
from transfers import services as transfers

PASSWORD = "arara-demo-2026"
TZ = ZoneInfo(settings.TIME_ZONE)
D = Decimal


class Clock:
    """The seed's time. Services and auto_now fields read it through timezone.now."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def forward_to(self, day: datetime, hour: int, minute: int = 0) -> None:
        """That time of the day, or a minute after now if it's already past: time never goes back."""
        target = datetime.combine(day.date(), time(hour, minute), tzinfo=TZ)
        self.now = max(target, self.now + timedelta(minutes=1))

    def tick(self, minutes: int = 1) -> datetime:
        self.now += timedelta(minutes=minutes)
        return self.now


@contextmanager
def simulated(clock: Clock) -> Iterator[None]:
    with mock.patch("django.utils.timezone.now", side_effect=lambda: clock.now):
        yield


# ─── The catalog ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    reference: str
    name: str
    category: str
    grid: str
    colors: tuple[str, ...]
    price: str
    cost: str
    popularity: int  # relative chance of being picked by a customer
    collection: str | None = None
    brand: str = "Arara"
    out_of_season: bool = False  # stops selling halfway: the stale stock report finds it


ITEMS = (
    Item(
        "CAM-001",
        "Camiseta básica algodão",
        "Camisetas",
        "Letras",
        ("Preto", "Branco", "Cinza mescla", "Azul marinho"),
        "59.90",
        "22.00",
        12,
        "Verão 2026",
    ),
    Item(
        "CAM-002",
        "Camiseta estampada arara",
        "Camisetas",
        "Letras",
        ("Branco", "Preto"),
        "89.90",
        "31.50",
        7,
        "Verão 2026",
    ),
    Item(
        "POL-001",
        "Polo piquet",
        "Camisetas",
        "Letras",
        ("Azul marinho", "Branco", "Verde oliva"),
        "129.90",
        "48.00",
        4,
        brand="Costa Norte",
    ),
    Item(
        "CAL-010",
        "Calça jeans reta",
        "Calças",
        "Numeração",
        ("Jeans escuro", "Jeans claro"),
        "199.90",
        "78.00",
        5,
        brand="Índigo",
    ),
    Item(
        "CAL-020",
        "Calça sarja chino",
        "Calças",
        "Numeração",
        ("Bege", "Preto", "Verde oliva"),
        "179.90",
        "66.00",
        3,
        brand="Costa Norte",
    ),
    Item(
        "BER-001",
        "Bermuda sarja",
        "Bermudas",
        "Numeração",
        ("Bege", "Azul marinho"),
        "119.90",
        "42.00",
        4,
        "Verão 2026",
    ),
    Item(
        "VES-001",
        "Vestido midi floral",
        "Vestidos",
        "Letras",
        ("Vermelho", "Azul marinho"),
        "249.90",
        "92.00",
        3,
        "Verão 2026",
    ),
    Item("VES-002", "Vestido tubinho", "Vestidos", "Letras", ("Preto",), "189.90", "70.00", 2),
    Item(
        "JAQ-001",
        "Jaqueta jeans",
        "Jaquetas",
        "Letras",
        ("Jeans claro",),
        "299.90",
        "118.00",
        2,
        "Inverno 2026",
        "Índigo",
        True,
    ),
    Item(
        "MOL-001",
        "Moletom canguru",
        "Jaquetas",
        "Letras",
        ("Cinza mescla", "Preto"),
        "219.90",
        "84.00",
        2,
        "Inverno 2026",
        out_of_season=True,
    ),
    Item(
        "TEN-001",
        "Tênis casual lona",
        "Calçados",
        "Calçados",
        ("Branco", "Preto"),
        "229.90",
        "95.00",
        3,
        brand="Passo Leve",
    ),
    Item(
        "TEN-002",
        "Tênis de corrida",
        "Calçados",
        "Calçados",
        ("Preto", "Azul marinho"),
        "399.90",
        "170.00",
        1,
        brand="Passo Leve",
    ),
    Item(
        "SAN-001",
        "Sandália rasteira",
        "Calçados",
        "Calçados",
        ("Bege", "Preto"),
        "99.90",
        "34.00",
        2,
        "Verão 2026",
        "Passo Leve",
    ),
)

GRIDS = {
    "Letras": ["PP", "P", "M", "G", "GG"],
    "Numeração": ["36", "38", "40", "42", "44", "46"],
    "Calçados": ["34", "35", "36", "37", "38", "39", "40", "41", "42", "43"],
}
# How sizes sell: the middle of the grid, mostly. The same weights size the purchases.
SIZE_WEIGHTS = {
    "Letras": [1, 3, 5, 4, 2],
    "Numeração": [1, 3, 5, 5, 3, 1],
    "Calçados": [1, 1, 2, 3, 4, 4, 4, 3, 2, 1],
}
COLORS = {
    "Preto": ("PRE", "#1c1917"),
    "Branco": ("BRA", "#ffffff"),
    "Cinza mescla": ("CIM", "#a8a29e"),
    "Azul marinho": ("AZM", "#1e3a5f"),
    "Verde oliva": ("VOL", "#5b6236"),
    "Bege": ("BEG", "#d6c3a0"),
    "Vermelho": ("VER", "#b91c1c"),
    "Jeans claro": ("JCL", "#8fb3d9"),
    "Jeans escuro": ("JES", "#2b3f63"),
}


# ─── The story ─────────────────────────────────────────────────────────────────


class Seed:
    def __init__(self, days: int, rng_seed: int = 2026) -> None:
        self.days = days
        self.rng = random.Random(rng_seed)
        today = timezone.localdate()
        self.first_day = datetime.combine(today - timedelta(days=days), time(8), tzinfo=TZ)
        self.clock = Clock(self.first_day)
        self.log: list[str] = []

    # Setup ----------------------------------------------------------------------

    def people_and_places(self) -> None:
        for code, name, kind in (("TRANSITO", "Em trânsito", "transit"), ("PERDAS", "Perdas", "loss")):
            Location.objects.get_or_create(kind=kind, defaults={"code": code, "name": name})
        self.centro = Location.objects.create(
            code="CENTRO", name="Loja Centro", kind=Location.Kind.STORE, cnpj=cnpj("123456780001")
        )
        self.shop = Location.objects.create(
            code="SHOP", name="Loja Shopping", kind=Location.Kind.STORE, cnpj=cnpj("123456780002")
        )
        self.dep = Location.objects.create(code="DEP", name="Depósito", kind=Location.Kind.WAREHOUSE)
        self.stores = [self.centro, self.shop]
        self.registers = {
            self.centro.pk: CashRegister.objects.create(location=self.centro, name="Caixa 1"),
            self.shop.pk: CashRegister.objects.create(location=self.shop, name="Caixa 1"),
        }
        CashRegister.objects.create(location=self.centro, name="Caixa 2")

        def person(email: str, name: str, role: Role, places: list[Location]) -> User:
            user = User.objects.create_user(email=email, name=name, role=role, password=PASSWORD)
            user.locations.set(places)
            return user

        self.owner = person("marta@arara.test", "Marta Souza", Role.OWNER, [])
        self.managers = {
            self.centro.pk: person("rafael@arara.test", "Rafael Lima", Role.MANAGER, [self.centro, self.dep]),
            self.shop.pk: person("lia@arara.test", "Lia Campos", Role.MANAGER, [self.shop]),
        }
        self.cashiers = {
            self.centro.pk: [
                person("bia@arara.test", "Bia Santos", Role.CASHIER, [self.centro]),
                person("davi@arara.test", "Davi Rocha", Role.CASHIER, [self.centro]),
            ],
            self.shop.pk: [person("caio@arara.test", "Caio Nunes", Role.CASHIER, [self.shop])],
        }
        self.stockist = person("joao@arara.test", "João Pereira", Role.STOCKIST, [self.dep, self.centro, self.shop])

    def catalog(self) -> None:
        grids = {}
        for name, labels in GRIDS.items():
            grid = SizeGrid.objects.create(name=name)
            Size.objects.bulk_create(Size(grid=grid, label=label, position=i) for i, label in enumerate(labels, 1))
            grids[name] = grid
        colors = {name: Color.objects.create(name=name, code=code, hex=hex_) for name, (code, hex_) in COLORS.items()}
        categories = {name: Category.objects.create(name=name) for name in sorted({i.category for i in ITEMS})}
        brands = {name: Brand.objects.create(name=name) for name in sorted({i.brand for i in ITEMS})}
        start = self.first_day.date()
        collections = {
            "Verão 2026": Collection.objects.create(
                name="Verão 2026", starts_on=start, ends_on=start + timedelta(days=150)
            ),
            "Inverno 2026": Collection.objects.create(
                name="Inverno 2026", starts_on=start - timedelta(days=120), ends_on=start + timedelta(days=20)
            ),
        }
        self.products: list[tuple[Item, Product]] = []
        for item in ITEMS:
            product = catalog.create_product(
                user=self.owner,
                colors=[colors[c] for c in item.colors],
                price=D(item.price),
                reference=item.reference,
                name=item.name,
                category=categories[item.category],
                brand=brands[item.brand],
                collection=collections.get(item.collection or ""),
                size_grid=grids[item.grid],
                ncm="61091000" if item.category == "Camisetas" else "",
                origin="0",
            )
            self.products.append((item, product))
        self.suppliers = [
            Supplier.objects.create(
                name="Malharia Serra Azul", cnpj=cnpj("SERRAAZUL001"), contact="Paula", email="vendas@serraazul.test"
            ),
            Supplier.objects.create(
                name="Índigo Confecções", cnpj=cnpj("448871230001"), contact="Marcos", phone="(11) 3333-0000"
            ),
            Supplier.objects.create(name="Passo Leve Calçados", cnpj=cnpj("PASSOLEVE001"), contact="Renata"),
        ]

    # Stock ----------------------------------------------------------------------

    def _supplier_of(self, item: Item) -> Supplier:
        return (
            self.suppliers[2]
            if item.category == "Calçados"
            else self.suppliers[1]
            if item.brand == "Índigo"
            else self.suppliers[0]
        )

    def _variants(self, product: Product) -> list[tuple[ProductVariant, int]]:
        """SKUs with their size weight."""
        labels = GRIDS[product.size_grid.name]
        weights = SIZE_WEIGHTS[product.size_grid.name]
        return [
            (v, weights[labels.index(v.size.label)]) for v in product.variants.select_related("size").order_by("pk")
        ]

    def buy(
        self, location: Location, scale: int, *, receive: bool = True, partial: bool = False
    ) -> list[PurchaseOrder]:
        """One order per supplier, quantities by size weight. Received in full unless told otherwise."""
        by_supplier: dict[int, list[purchasing.OrderLineInput]] = {}
        for item, product in self.products:
            if item.out_of_season and self.clock.now > self.first_day:  # winter isn't bought again
                continue
            for variant, weight in self._variants(product):
                quantity = max(1, weight * scale * item.popularity // 6)
                cost = D(item.cost) * D(self.rng.choice(["0.97", "1.00", "1.00", "1.03"]))
                line = purchasing.OrderLineInput(variant, quantity, cost.quantize(D("0.01")))
                by_supplier.setdefault(self._supplier_of(item).pk, []).append(line)
        orders = []
        for supplier in self.suppliers:
            lines = by_supplier.get(supplier.pk)
            if not lines:
                continue
            order = purchasing.create_order(
                user=self.owner,
                supplier=supplier,
                location=location,
                lines=lines,
                expected_on=(self.clock.now + timedelta(days=7)).date(),
            )
            self.clock.tick(5)
            purchasing.send_order(user=self.owner, order=order)
            orders.append(order)
            if receive:
                # Delivered the same evening: the clock never jumps ahead of the next day's sales,
                # so the ledger stays in the order things happened.
                self.clock.tick(60)
                order_lines = list(order.lines.all())
                if partial:  # some boxes didn't come: received later or the order is closed short
                    order_lines = order_lines[: len(order_lines) * 2 // 3]
                purchasing.receive(
                    user=self.stockist,
                    order=order,
                    lines=[purchasing.ReceiptLineInput(line.pk, line.quantity_ordered) for line in order_lines],
                    invoice_number=str(self.rng.randint(10_000, 99_999)),
                )
        return orders

    def restock(self, store: Location) -> None:
        """Send from the warehouse what the store is short of, up to its maximum."""
        lines = []
        warehouse = {
            lvl.variant_id: lvl.quantity for lvl in StockLevel.objects.filter(location=self.dep, quantity__gt=0)
        }
        for level in StockLevel.objects.filter(location=store, quantity__lt=F("min_quantity")).select_related(
            "variant"
        ):
            wanted = (level.max_quantity or level.min_quantity * 2) - level.quantity
            available = warehouse.get(level.variant_id, 0)
            if min(wanted, available) > 0:
                lines.append((level.variant, min(wanted, available)))
        if not lines:
            return
        trip = transfers.create(user=self.stockist, origin=self.dep, destination=store, lines=lines)
        transfers.dispatch(user=self.stockist, transfer=trip)
        self.clock.tick(60 * 5)
        received = {line.pk: line.quantity_sent for line in trip.lines.all()}
        if self.rng.random() < 0.2:  # a piece went missing on the way
            first = next(iter(received))
            received[first] -= 1
        transfers.receive(
            user=self.managers[store.pk], transfer=trip, received=received, missing_reason="Faltou uma peça na caixa"
        )

    def set_targets(self) -> None:
        for item, product in self.products:
            for variant, weight in self._variants(product):
                StockLevel.objects.filter(variant=variant, location__in=self.stores).update(
                    min_quantity=max(1, weight * item.popularity // 8),
                    max_quantity=max(2, weight * item.popularity // 3),
                )

    # Selling --------------------------------------------------------------------

    def _pick(self, store: Location, selling: list[tuple[Item, Product]]) -> tuple[ProductVariant, int] | None:
        for _ in range(8):
            _, product = self.rng.choices(selling, weights=[i.popularity for i, _ in selling])[0]
            variants = self._variants(product)
            variant = self.rng.choices([v for v, _ in variants], weights=[w for _, w in variants])[0]
            level = (
                StockLevel.objects.filter(variant=variant, location=store).values_list("quantity", flat=True).first()
            )
            if level:
                return variant, min(level, self.rng.choices([1, 1, 1, 2, 3])[0])
        return None

    def _payments(self, total: Decimal) -> list[pos.PaymentInput]:
        method = self.rng.choices(["pix", "credit", "debit", "cash"], weights=[35, 30, 20, 15])[0]
        if method == "cash":
            tendered = (total / 10).quantize(D("1"), rounding=ROUND_CEILING) * 10
            return [pos.PaymentInput(Payment.Method.CASH, total, tendered=tendered)]
        if method == "credit":
            return [pos.PaymentInput(Payment.Method.CREDIT, total, installments=self.rng.choice([1, 1, 2, 3, 4, 6]))]
        return [pos.PaymentInput(Payment.Method(method), total)]

    def _sell(self, store: Location, cashier: User, selling: list[tuple[Item, Product]]) -> Sale | None:
        lines: dict[int, tuple[ProductVariant, int]] = {}
        for _ in range(self.rng.choices([1, 1, 2, 3])[0]):
            picked = self._pick(store, selling)
            if picked and picked[0].pk not in lines:
                lines[picked[0].pk] = picked
        if not lines:
            return None
        subtotal = sum((catalog.current_price(v) or D(0)) * q for v, q in lines.values())
        roll = self.rng.random()
        percent = D("15") if roll < 0.03 else D("5") if roll < 0.18 else D("0")
        discount = (subtotal * percent / 100).quantize(D("0.01"), rounding=ROUND_DOWN)  # never above the percent
        approval = None
        if percent > settings.POS_CASHIER_MAX_DISCOUNT_PERCENT:
            approval = grant_approval(
                request=None,
                requester=cashier,
                approver_email=self.managers[store.pk].email,
                approver_password=PASSWORD,
                action=Approval.Action.DISCOUNT,
                location=store,
                reason="Cliente fiel",
                limit=percent,
            )
        salespeople = [self.managers[store.pk], *self.cashiers[store.pk]]
        sale, _ = pos.create_sale(
            user=cashier,
            client_request_id=self._uuid(),
            items=[pos.ItemInput(v, q) for v, q in lines.values()],
            payments=self._payments(subtotal - discount),
            discount=discount,
            salesperson=self.rng.choice(salespeople) if self.rng.random() < 0.8 else None,
            approval_id=approval.pk if approval else None,
        )
        return sale

    def sell_day(self, day: datetime, plan: dict[Location, int]) -> list[Sale]:
        """
        Both stores' day, interleaved by the clock: the average cost is company-wide, so the
        ledger must take the sales in the order they happened, whatever the store.
        """
        selling = [
            (i, p)
            for i, p in self.products
            if not (i.out_of_season and day > self.first_day + timedelta(days=self.days // 3))
        ]
        tills: dict[int, tuple[User, CashSession]] = {}
        for store in plan:
            cashier = self.rng.choice(self.cashiers[store.pk])
            self.clock.forward_to(day, 10)
            tills[store.pk] = (
                cashier,
                pos.open_session(user=cashier, register=self.registers[store.pk], opening_float=D("100.00")),
            )
        # (minute of the day, store, what): sales in their own slot of 10:00-20:00, a cash pick-up at 15:00.
        events: list[tuple[int, Location, str]] = []
        for store, count in plan.items():
            slot = 600 // max(count, 1)
            events += [(600 + n * slot + self.rng.randint(0, slot - 1), store, "sale") for n in range(count)]
            if self.rng.random() < 0.3:
                events.append((900, store, "withdrawal"))
        sold: list[Sale] = []
        for minute, store, what in sorted(events, key=lambda e: e[0]):
            self.clock.forward_to(day, minute // 60, minute % 60)
            cashier, session = tills[store.pk]
            if what == "withdrawal":
                if pos.expected_cash(session) > D("300"):
                    pos.move_cash(
                        user=cashier,
                        session=session,
                        kind=CashMovement.Kind.WITHDRAWAL,
                        amount=D("200.00"),
                        reason="Cofre",
                    )
                continue
            sale = self._sell(store, cashier, selling)
            if sale is None:
                continue
            if self.rng.random() < 0.015:  # the customer gave up at the counter
                self.clock.tick(1)
                pos.cancel_sale(user=cashier, sale=sale, reason="Cliente desistiu")
            else:
                sold.append(sale)
        for cashier, session in tills.values():
            self.clock.forward_to(day, 21, 10)
            self.clock.tick(1)
            expected = pos.expected_cash(session)
            slip = self.rng.choices([D("0"), D("-2.00"), D("0.50"), D("-10.00")], weights=[85, 8, 5, 2])[0]
            pos.close_session(
                user=cashier,
                session=session,
                counted_cash=max(expected + slip, D(0)),
                note="" if not slip else "Conferido duas vezes",
            )
        return sold

    def returns(self, day: datetime, recent: list[Sale]) -> None:
        """A few customers come back: some for a credit, some to exchange on the spot."""
        for sale in recent:
            if self.rng.random() > 0.03:
                continue
            item = sale.items.order_by("pk").first()
            if item is None or item.quantity_returned:
                continue
            store = sale.location
            cashier = self.cashiers[store.pk][0]
            self.clock.forward_to(day, 20, 30 + self.rng.randint(0, 20))  # after the day's sales, before closing
            pos.return_items(
                user=cashier,
                location=store,
                lines=[pos.ReturnInput(quantity=1, sale_item_id=item.pk)],
                refund_method=SaleReturn.Refund.STORE_CREDIT,
                reason=self.rng.choice(["Não serviu", "Trocou de ideia", "Presente repetido"]),
                original_sale=sale,
            )

    def count(self, store: Location) -> None:
        """A blind count of the T-shirts: two pieces are not where the system says."""
        shirts = Category.objects.get(name="Camisetas")
        session = counts.open_count(
            user=self.managers[store.pk], location=store, category_ids=[shirts.pk], note="Contagem mensal"
        )
        levels = list(
            StockLevel.objects.filter(location=store, variant__product__category=shirts, quantity__gt=0).select_related(
                "variant"
            )
        )
        missing = {lvl.pk for lvl in self.rng.sample(levels, k=min(2, len(levels)))}
        for level in levels:
            self.clock.tick(1)
            counts.add_entry(
                user=self.stockist,
                count=session,
                code=level.variant.sku,
                quantity=level.quantity - (1 if level.pk in missing else 0),
                area="Arara da frente",
            )
        counts.finish(user=self.managers[store.pk], count=session)
        self.clock.tick(30)
        counts.apply(user=self.managers[store.pk], count=session, uncounted="keep")

    def _uuid(self) -> uuid.UUID:
        return uuid.UUID(int=self.rng.getrandbits(128), version=4)

    # The whole story ------------------------------------------------------------

    def run(self) -> None:
        with simulated(self.clock):
            # Opening stock arrives the week before the history starts.
            self.clock.now = self.first_day - timedelta(days=7)
            self.people_and_places()
            self.catalog()
            self.buy(self.dep, scale=4)
            for store in self.stores:
                self.buy(store, scale=2)
            self.set_targets()
            yesterday: list[Sale] = []
            for offset in range(self.days):
                day = self.first_day + timedelta(days=offset)
                weekend = day.weekday() >= 5
                plan = {
                    store: (9 if store == self.centro else 6) + (4 if weekend else 0) + self.rng.randint(-2, 2)
                    for store in self.stores
                }
                today_sales = self.sell_day(day, plan)
                self.returns(day, yesterday)  # yesterday's customers come back in the evening
                yesterday = today_sales
                if offset % 7 in (2, 6):  # the van goes round twice a week
                    self.clock.forward_to(day, 22)
                    for store in self.stores:
                        self.restock(store)
                if offset % 14 == 13 and offset < self.days - 3:
                    self.clock.forward_to(day, 22, 30)
                    self.buy(self.dep, scale=2, partial=offset % 28 == 27)
                if offset == self.days - 10:
                    self.clock.forward_to(day, 22, 40)
                    self.count(self.shop)
                if offset == self.days // 2:  # the winter pieces go on sale
                    self.clock.forward_to(day, 22, 50)
                    for item, product in self.products:
                        if item.out_of_season:
                            markdown = D(int(D(item.price) * D("0.7"))) + D("0.90")  # 30% off, ending in ,90
                            catalog.set_price(user=self.owner, product=product, amount=markdown)
        # Today: work in progress for the demo to pick up.
        now = timezone.now()
        self.clock.now = now - timedelta(hours=1)
        with simulated(self.clock):
            self.buy(self.dep, scale=1, receive=False)  # sent, waiting at the dock
            levels = StockLevel.objects.filter(location=self.dep, quantity__gte=4).select_related("variant")[:3]
            if levels:
                trip = transfers.create(
                    user=self.stockist,
                    origin=self.dep,
                    destination=self.shop,
                    lines=[(lvl.variant, 2) for lvl in levels],
                )
                transfers.dispatch(user=self.stockist, transfer=trip)
            catalog.set_price(
                user=self.owner,
                product=self.products[0][1],
                amount=D("49.90"),
                valid_from=now + timedelta(days=10),
            )


def restart_sequences() -> None:
    with connection.cursor() as cursor:
        cursor.execute("alter sequence purchasing_order_number_seq restart")
        cursor.execute("alter sequence transfers_number_seq restart")


def summary() -> dict[str, object]:
    return {
        "sales": Sale.objects.filter(status=Sale.Status.COMPLETED).count(),
        "revenue": Sale.objects.filter(status=Sale.Status.COMPLETED).aggregate(total=Sum("total"))["total"],
        "returns": SaleReturn.objects.count(),
        "pieces_in_stock": StockLevel.objects.aggregate(total=Sum("quantity"))["total"],
    }
