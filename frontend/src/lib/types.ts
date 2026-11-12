/** The API's shapes (see /api/docs). Money and costs are decimal strings. */

export type Role = 'owner' | 'manager' | 'cashier' | 'stockist';
export type Capability =
  | 'users.manage'
  | 'locations.manage'
  | 'catalog.manage'
  | 'prices.change'
  | 'costs.view'
  | 'stock.view'
  | 'stock.adjust'
  | 'purchasing.manage'
  | 'stock.receive'
  | 'stock.transfer'
  | 'stock.count'
  | 'stock.count_apply'
  | 'pos.sell'
  | 'pos.cash'
  | 'approvals.grant'
  | 'reports.sales'
  | 'reports.margin'
  | 'audit.view';

export interface LocationRef {
  id: number;
  code: string;
  name: string;
  kind: 'store' | 'warehouse';
}

export interface Me {
  id: number;
  email: string;
  name: string;
  role: Role;
  role_label: string;
  capabilities: Capability[];
  locations: LocationRef[];
}

export interface Location extends LocationRef {
  is_active: boolean;
  cnpj: string;
  state_registration: string;
}

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  role_label: string;
  locations: number[];
  is_active: boolean;
  date_joined: string;
}

// ─── Catalog ─────────────────────────────────────────────────────────────────

export interface Named {
  id: number;
  name: string;
  is_active: boolean;
}

export interface Collection extends Named {
  starts_on: string | null;
  ends_on: string | null;
}

export interface Color {
  id: number;
  name: string;
  code: string;
  hex: string;
}

export interface SizeGrid {
  id: number;
  name: string;
  sizes: { id: number; label: string; position: number }[];
}

export interface Barcode {
  code: string;
  kind: 'internal' | 'supplier';
}

export interface Variant {
  id: number;
  sku: string;
  size: string;
  size_position: number;
  color: Color;
  is_active: boolean;
  barcodes: Barcode[];
  current_price: string | null;
}

export interface ProductListItem {
  id: number;
  reference: string;
  name: string;
  category: string;
  brand: string | null;
  collection: string | null;
  is_active: boolean;
  current_price: string | null;
  variant_count: number;
}

export interface Product {
  id: number;
  reference: string;
  name: string;
  description: string;
  category: number;
  brand: number | null;
  collection: number | null;
  size_grid: SizeGrid;
  ncm: string;
  cest: string;
  origin: string;
  is_active: boolean;
  current_price: string | null;
  variants: Variant[];
}

export interface Price {
  id: number;
  variant: number | null;
  sku: string | null;
  amount: string;
  valid_from: string;
  created_by: string;
  created_at: string;
}

/** A scan resolved: one SKU, with its product and today's price. */
export interface Lookup {
  id: number;
  sku: string;
  product: { id: number; reference: string; name: string };
  size: string;
  color: string;
  is_active: boolean;
  current_price: string | null;
}

// ─── Stock ───────────────────────────────────────────────────────────────────

export interface StockLevel {
  id: number;
  variant: number;
  sku: string;
  reference: string;
  product: string;
  size: string;
  color: string;
  location: number;
  location_code: string;
  quantity: number;
  min_quantity: number;
  max_quantity: number | null;
  below_min: boolean;
  average_cost?: string | null;
  stock_value?: string | null;
}

export interface Movement {
  id: number;
  entry: number;
  kind: string;
  kind_label: string;
  reason: string;
  note: string;
  source_ref: string;
  created_by: string;
  created_at: string;
  variant: number;
  sku: string;
  location: number;
  location_code: string;
  quantity_delta: number;
  balance_after: number;
  value_delta?: string;
  unit_cost?: string;
}

export interface Grid {
  product: string;
  sizes: string[];
  rows: { color: string; quantities: number[] }[];
}

export type AdjustmentReason = 'damaged' | 'theft' | 'found' | 'error' | 'other';

// ─── Purchasing ──────────────────────────────────────────────────────────────

export interface Supplier {
  id: number;
  name: string;
  cnpj: string;
  contact: string;
  email: string;
  phone: string;
  notes: string;
  is_active: boolean;
}

export type OrderStatus = 'draft' | 'sent' | 'partially_received' | 'received' | 'closed' | 'cancelled';

export interface OrderLine {
  id: number;
  variant: number;
  sku: string;
  product: string;
  size: string;
  color: string;
  quantity_ordered: number;
  quantity_received: number;
  pending: number;
  unit_cost?: string;
}

export interface Order {
  id: number;
  number: string;
  supplier: number;
  supplier_name: string;
  location: number;
  location_code: string;
  status: OrderStatus;
  status_label: string;
  expected_on: string | null;
  notes: string;
  created_by: string;
  created_at: string;
  sent_at: string | null;
  finished_at: string | null;
  finish_reason: string;
  lines: OrderLine[];
  total_cost?: string;
}

export interface Receipt {
  id: number;
  order: number;
  order_number: string;
  invoice_number: string;
  received_by: string;
  received_at: string;
  cancelled_at: string | null;
  lines: { id: number; order_line: number; sku: string; quantity: number; unit_cost?: string }[];
}

export interface Suggestion {
  location: number;
  location_code: string;
  variant: number;
  sku: string;
  product: string;
  quantity: number;
  on_order: number;
  min_quantity: number;
  max_quantity: number | null;
  suggested: number;
  last_supplier: number | null;
  last_unit_cost?: string | null;
}

// ─── Transfers and counts ────────────────────────────────────────────────────

export type TransferStatus = 'draft' | 'in_transit' | 'received' | 'cancelled';

export interface Transfer {
  id: number;
  number: string;
  origin: number;
  origin_code: string;
  destination: number;
  destination_code: string;
  status: TransferStatus;
  status_label: string;
  notes: string;
  created_by: string;
  created_at: string;
  dispatched_by: string | null;
  dispatched_at: string | null;
  received_by: string | null;
  received_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string;
  lines: {
    id: number;
    variant: number;
    sku: string;
    product: string;
    size: string;
    color: string;
    quantity_sent: number;
    quantity_received: number | null;
  }[];
}

export type CountStatus = 'counting' | 'review' | 'applied' | 'cancelled';

export interface Count {
  id: number;
  location: number;
  location_code: string;
  status: CountStatus;
  status_label: string;
  scope_label: string;
  tolerance: number;
  note: string;
  opened_by: string;
  opened_at: string;
  finished_at: string | null;
  applied_at: string | null;
  scope_size: number;
  counted_skus: number;
}

export interface CountEntry {
  id: number;
  variant: number;
  sku: string;
  area: string;
  quantity: number;
  counted_by: string;
  created_at: string;
}

// ─── Point of sale ───────────────────────────────────────────────────────────

export type PaymentMethod = 'cash' | 'debit' | 'credit' | 'pix' | 'store_credit';

export interface Register {
  id: number;
  location: number;
  location_code: string;
  name: string;
  is_active: boolean;
  open_session: { id: number; opened_by: string } | null;
}

export interface SessionSummary {
  opening_float: string;
  sales: number;
  cancelled_sales: number;
  by_method: Partial<Record<PaymentMethod, string>>;
  movements: Partial<Record<'withdrawal' | 'supply' | 'refund', string>>;
  expected_cash: string | null;
  counted_cash: string | null;
  difference: string | null;
}

export interface CashSession {
  id: number;
  register: number;
  register_name: string;
  location: number;
  opened_by: string;
  opened_at: string;
  opening_float: string;
  closed_by: string | null;
  closed_at: string | null;
  expected_cash: string | null;
  counted_cash: string | null;
  closing_note: string;
  summary?: SessionSummary;
}

export interface SaleItem {
  id: number;
  variant: number;
  sku: string;
  product: string;
  size: string;
  color: string;
  quantity: number;
  quantity_returned: number;
  unit_price: string;
  discount: string;
  net_amount: string;
  cost_value?: string;
  margin?: string;
}

export interface Payment {
  method: PaymentMethod;
  method_label: string;
  amount: string;
  tendered: string | null;
  change: string | null;
  installments: number | null;
  card_brand: string;
  nsu: string;
}

export interface Sale {
  id: number;
  location: number;
  location_code: string;
  number: number;
  status: 'completed' | 'cancelled';
  status_label: string;
  cashier: string;
  salesperson: string | null;
  customer: string | null;
  subtotal: string;
  discount_total: string;
  total: string;
  created_at: string;
  cancelled_at: string | null;
  cancel_reason: string;
  items: SaleItem[];
  payments: Payment[];
}

export interface SaleReturn {
  id: number;
  location: number;
  location_code: string;
  original_sale: number | null;
  sale_number: number | null;
  refund_method: 'cash' | 'store_credit';
  total: string;
  reason: string;
  store_credit: string | null;
  created_by: string;
  created_at: string;
  lines: { id: number; sale_item: number | null; variant: number; sku: string; quantity: number; refund_amount: string }[];
}

export interface StoreCredit {
  code: string;
  customer: string | null;
  balance: string;
  expires_on: string | null;
  created_at: string;
}

export interface Customer {
  id: number;
  name: string;
  cpf: string;
  email: string;
  phone: string;
}

export interface Approval {
  id: number;
  action: 'discount' | 'return_without_receipt' | 'stock_adjustment';
  location: number;
  approver_name: string;
  reason: string;
  limit: string | null;
  expires_at: string;
}
