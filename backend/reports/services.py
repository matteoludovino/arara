"""
Reports, computed from the documents and the stock ledger.

Definitions (also in the README):
- Net sales: completed sales in the period minus returns made in the period (by return date).
  Cancelled sales count for nothing.
- Cost of goods sold (CMV): the cost frozen on each sale item, minus the cost that came back
  with returns. Margin = net sales - CMV.
- Stock value at a moment: per SKU, the company-wide quantity and value up to that moment
  come from the ledger (inventory locations only); a location's value is its quantity at that
  moment times that average. Summed over locations it equals the ledger total.
- Turnover (giro): CMV / average stock value (mean of the start and end of the period).
  Coverage: pieces in stock / average pieces sold per day.
- ABC: products ranked by net revenue. A product is A while the share accumulated before it
  is under 80%, B under 95%, C after: the product that crosses a line stays in the class above.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Max, QuerySet, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from catalog.models import Product
from common.errors import DomainError
from locations.models import Location
from pos.models import ReturnLine, Sale, SaleItem, SaleReturn
from purchasing.models import GoodsReceipt
from stock.models import StockLevel, StockMovement

ZERO = Decimal("0")
MAX_DAYS = 366


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def percent(part: Decimal, whole: Decimal) -> str | None:
    return str((part * 100 / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if whole else None


@dataclass(frozen=True)
class Period:
    first: date
    last: date

    @property
    def start(self) -> datetime:
        return datetime.combine(self.first, time.min, tzinfo=ZoneInfo(settings.TIME_ZONE))

    @property
    def end(self) -> datetime:
        """Exclusive: midnight after the last day."""
        return datetime.combine(self.last + timedelta(days=1), time.min, tzinfo=ZoneInfo(settings.TIME_ZONE))

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def period(first: date | None, last: date | None) -> Period:
    last = last or timezone.localdate()
    first = first or last - timedelta(days=29)
    if first > last:
        raise DomainError("A data inicial é depois da final.", "period_inverted")
    if (last - first).days >= MAX_DAYS:
        raise DomainError(f"Período de no máximo {MAX_DAYS} dias.", "period_too_long")
    return Period(first, last)


def _sales(locations: list[int], span: Period) -> QuerySet[Sale]:
    return Sale.objects.filter(
        status=Sale.Status.COMPLETED, location_id__in=locations, created_at__gte=span.start, created_at__lt=span.end
    )


def _returns(locations: list[int], span: Period) -> QuerySet[SaleReturn]:
    return SaleReturn.objects.filter(location_id__in=locations, created_at__gte=span.start, created_at__lt=span.end)


# ─── Sales ─────────────────────────────────────────────────────────────────────


@dataclass
class Totals:
    sales: int = 0
    units: int = 0
    gross: Decimal = ZERO
    discounts: Decimal = ZERO
    sold: Decimal = ZERO  # completed sales, after discounts
    returns: Decimal = ZERO
    cogs: Decimal = ZERO

    def add(self, other: Totals) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def shape(self) -> dict[str, object]:
        net = self.sold - self.returns
        return {
            "sales": self.sales,
            "units": self.units,
            "gross": money(self.gross),
            "discounts": money(self.discounts),
            "returns": money(self.returns),
            "net": money(net),
            "average_ticket": money(self.sold / self.sales) if self.sales else None,
            "cogs": money(self.cogs),
            "margin": money(net - self.cogs),
            "margin_percent": percent(net - self.cogs, net),
        }


def sales_summary(locations: list[int], span: Period) -> dict[str, object]:
    tz = ZoneInfo(settings.TIME_ZONE)
    sales, returns = _sales(locations, span), _returns(locations, span)
    days: dict[date, Totals] = defaultdict(Totals)
    for row in (
        sales.annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day")
        .annotate(sales=Count("id"), gross=Sum("subtotal"), discounts=Sum("discount_total"), sold=Sum("total"))
    ):
        day = days[row["day"]]
        day.sales, day.gross, day.discounts, day.sold = row["sales"], row["gross"], row["discounts"], row["sold"]
    for item in (
        SaleItem.objects.filter(sale__in=sales)
        .annotate(day=TruncDate("sale__created_at", tzinfo=tz))
        .values("day")
        .annotate(cogs=Sum("cost_value"), units=Sum("quantity"))
    ):
        days[item["day"]].cogs += item["cogs"]
        days[item["day"]].units += item["units"]
    for back in (
        ReturnLine.objects.filter(sale_return__in=returns)
        .annotate(day=TruncDate("sale_return__created_at", tzinfo=tz))
        .values("day")
        .annotate(refunds=Sum("refund_amount"), cost=Sum("cost_value"), units=Sum("quantity"))
    ):
        day = days[back["day"]]
        day.returns += back["refunds"]
        day.cogs -= back["cost"]
        day.units -= back["units"]
    total = Totals()
    for values in days.values():
        total.add(values)
    return {
        "from": span.first.isoformat(),
        "to": span.last.isoformat(),
        "days": [{"day": day.isoformat(), **values.shape()} for day, values in sorted(days.items())],
        "total": total.shape(),
    }


def by_salesperson(locations: list[int], span: Period) -> list[dict[str, object]]:
    returned = dict(
        ReturnLine.objects.filter(sale_return__in=_returns(locations, span), sale_item__isnull=False)
        .values("sale_item__sale__salesperson")
        .annotate(refunds=Sum("refund_amount"))
        .values_list("sale_item__sale__salesperson", "refunds")
    )
    rows = [
        {
            "salesperson": row["salesperson"],
            "name": row["name"] or "Sem vendedor",
            "sales": row["sales"],
            "net": money(row["total"] - returned.get(row["salesperson"], ZERO)),
            "average_ticket": money(row["total"] / row["sales"]),
        }
        for row in _sales(locations, span)
        .values("salesperson")
        .annotate(name=Max("salesperson__name"), sales=Count("id"), total=Sum("total"))
    ]
    return sorted(rows, key=lambda r: Decimal(str(r["net"])), reverse=True)


def _net_by_product(
    locations: list[int], span: Period
) -> tuple[dict[int, Decimal], dict[int, int], dict[int, Decimal]]:
    """Revenue, units and cost of goods sold per product, net of returns."""
    revenue: dict[int, Decimal] = defaultdict(lambda: ZERO)
    units: dict[int, int] = defaultdict(int)
    cogs: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for row in (
        SaleItem.objects.filter(sale__in=_sales(locations, span))
        .values("variant__product")
        .annotate(revenue=Sum("net_amount"), units=Sum("quantity"), cost=Sum("cost_value"))
    ):
        product = row["variant__product"]
        revenue[product] += row["revenue"]
        units[product] += row["units"]
        cogs[product] += row["cost"]
    for back in (
        ReturnLine.objects.filter(sale_return__in=_returns(locations, span))
        .values("variant__product")
        .annotate(refunds=Sum("refund_amount"), units=Sum("quantity"), cost=Sum("cost_value"))
    ):
        product = back["variant__product"]
        revenue[product] -= back["refunds"]
        units[product] -= back["units"]
        cogs[product] -= back["cost"]
    return revenue, units, cogs


def abc_curve(locations: list[int], span: Period) -> list[dict[str, object]]:
    revenue, units, _ = _net_by_product(locations, span)
    ranked = sorted(((pk, value) for pk, value in revenue.items() if value > 0), key=lambda kv: kv[1], reverse=True)
    total = sum((value for _, value in ranked), ZERO)
    names = {
        pk: (ref, name)
        for pk, ref, name in Product.objects.filter(pk__in=revenue).values_list("pk", "reference", "name")
    }
    rows: list[dict[str, object]] = []
    before = ZERO
    for pk, value in ranked:
        share_before = before * 100 / total
        klass = "A" if share_before < 80 else "B" if share_before < 95 else "C"
        before += value
        rows.append(
            {
                "product": pk,
                "reference": names[pk][0],
                "name": names[pk][1],
                "units": units[pk],
                "revenue": money(value),
                "share": percent(value, total),
                "cumulative_share": percent(before, total),
                "class": klass,
            }
        )
    return rows


def size_color_matrix(locations: list[int], span: Period, product: Product) -> dict[str, object]:
    sold: dict[tuple[str, str], int] = defaultdict(int)
    keys = ("variant__color__name", "variant__size__label")
    for row in (
        SaleItem.objects.filter(sale__in=_sales(locations, span), variant__product=product)
        .values(*keys)
        .annotate(units=Sum("quantity"))
    ):
        sold[(row[keys[0]], row[keys[1]])] += row["units"]
    for row in (
        ReturnLine.objects.filter(sale_return__in=_returns(locations, span), variant__product=product)
        .values(*keys)
        .annotate(units=Sum("quantity"))
    ):
        sold[(row[keys[0]], row[keys[1]])] -= row["units"]
    sizes = list(product.size_grid.sizes.values_list("label", flat=True))
    colors = list(product.variants.order_by("color__name").values_list("color__name", flat=True).distinct())
    rows = [{"color": c, "units": [sold.get((c, s), 0) for s in sizes]} for c in colors]
    return {
        "product": product.reference,
        "sizes": sizes,
        "rows": rows,
        "by_size": [sum(sold.get((c, s), 0) for c in colors) for s in sizes],
        "total": sum(sold.values()),
    }


# ─── Stock ─────────────────────────────────────────────────────────────────────


@dataclass
class StockValue:
    quantity: int = 0
    value: Decimal = ZERO
    by_location: dict[int, Decimal] = field(default_factory=lambda: defaultdict(lambda: ZERO))


def stock_value_at(moment: datetime, locations: list[int]) -> dict[int, StockValue]:
    """Pieces and value per product just before `moment`, at the company-wide average of each SKU then."""
    upto = StockMovement.objects.filter(entry__created_at__lt=moment)
    company = {
        variant: (quantity, value)
        for variant, quantity, value in upto.filter(location__kind__in=[str(k) for k in Location.INVENTORY_KINDS])
        .values("variant")
        .annotate(quantity=Sum("quantity_delta"), value=Sum("value_delta"))
        .values_list("variant", "quantity", "value")
    }
    result: dict[int, StockValue] = defaultdict(StockValue)
    for row in (
        upto.filter(location_id__in=locations)
        .values("variant", "variant__product", "location")
        .annotate(quantity=Sum("quantity_delta"))
        .filter(quantity__gt=0)
    ):
        total_quantity, total_value = company.get(row["variant"], (0, ZERO))
        value = total_value * row["quantity"] / total_quantity if total_quantity else ZERO
        entry = result[row["variant__product"]]
        entry.quantity += row["quantity"]
        entry.value += value
        entry.by_location[row["location"]] += value
    return result


def valuation(locations: list[int], moment: datetime) -> dict[str, object]:
    at = stock_value_at(moment, locations)
    codes = dict(Location.objects.filter(pk__in=locations).values_list("pk", "code"))
    by_location: dict[int, Decimal] = defaultdict(lambda: ZERO)
    by_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rows = []
    for pk, reference, name, category in Product.objects.filter(pk__in=list(at)).values_list(
        "pk", "reference", "name", "category__name"
    ):
        entry = at[pk]
        for location, value in entry.by_location.items():
            by_location[location] += value
        by_category[category] += entry.value
        rows.append(
            {
                "product": pk,
                "reference": reference,
                "name": name,
                "quantity": entry.quantity,
                "value": money(entry.value),
            }
        )
    return {
        "at": moment.isoformat(),
        "total": money(sum(by_location.values(), ZERO)),
        "by_location": [{"location": codes[loc], "value": money(v)} for loc, v in sorted(by_location.items())],
        "by_category": [
            {"category": c, "value": money(v)} for c, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        "products": sorted(rows, key=lambda r: -Decimal(str(r["value"]))),
    }


def turnover(locations: list[int], span: Period) -> list[dict[str, object]]:
    start = stock_value_at(span.start, locations)
    end = stock_value_at(min(span.end, timezone.now()), locations)
    _, units, cogs = _net_by_product(locations, span)
    in_stock = dict(
        StockLevel.objects.filter(location_id__in=locations)
        .values("variant__product")
        .annotate(quantity=Sum("quantity"))
        .values_list("variant__product", "quantity")
    )
    product_ids = {pk for pk, sold in units.items() if sold} | {pk for pk, quantity in in_stock.items() if quantity}
    names = {
        pk: (ref, name)
        for pk, ref, name in Product.objects.filter(pk__in=product_ids).values_list("pk", "reference", "name")
    }
    rows: list[dict[str, Any]] = []
    for pk in product_ids:
        stock = in_stock.get(pk, 0)
        daily = Decimal(units[pk]) / span.days
        average_value = (start[pk].value + end[pk].value) / 2
        rows.append(
            {
                "product": pk,
                "reference": names[pk][0],
                "name": names[pk][1],
                "units_sold": units[pk],
                "in_stock": stock,
                "coverage_days": int(stock / daily) if daily > 0 else None,
                "cogs": money(cogs[pk]),
                "average_stock_value": money(average_value),
                "turnover": str((cogs[pk] / average_value).quantize(Decimal("0.01"))) if average_value > 0 else None,
            }
        )
    # Shortest coverage first (about to run out); products that didn't sell at the end.
    return sorted(rows, key=lambda r: (r["coverage_days"] is None, r["coverage_days"] or 0))


def stale_products(locations: list[int], days: int) -> list[dict[str, object]]:
    """In stock here, no sale here for `days` days: candidates for a markdown or a transfer."""
    since = timezone.now() - timedelta(days=days)
    in_stock = dict(
        StockLevel.objects.filter(location_id__in=locations, quantity__gt=0)
        .values("variant__product")
        .annotate(quantity=Sum("quantity"))
        .values_list("variant__product", "quantity")
    )
    last_sale = dict(
        SaleItem.objects.filter(sale__status=Sale.Status.COMPLETED, sale__location_id__in=locations)
        .values("variant__product")
        .annotate(last=Max("sale__created_at"))
        .values_list("variant__product", "last")
    )
    last_receipt = dict(
        GoodsReceipt.objects.filter(order__location_id__in=locations, cancelled_at__isnull=True)
        .values("lines__order_line__variant__product")
        .annotate(last=Max("received_at"))
        .values_list("lines__order_line__variant__product", "last")
    )
    values = stock_value_at(timezone.now(), locations)
    stale = [pk for pk in in_stock if last_sale.get(pk) is None or last_sale[pk] < since]
    rows = [
        {
            "product": p.pk,
            "reference": p.reference,
            "name": p.name,
            "collection": p.collection.name if p.collection else None,
            "in_stock": in_stock[p.pk],
            "stock_value": money(values[p.pk].value),
            "last_sale": last_sale[p.pk].isoformat() if p.pk in last_sale else None,
            "last_receipt": last_receipt[p.pk].isoformat() if last_receipt.get(p.pk) else None,
        }
        for p in Product.objects.filter(pk__in=stale).select_related("collection")
    ]
    return sorted(rows, key=lambda r: -Decimal(str(r["stock_value"])))
