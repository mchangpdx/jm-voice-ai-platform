export interface VerticalMeta {
  icon: string;
  primaryRevenueLabel: string;
  conversionLabel: string;
  avgValueLabel: string;
  industryLabel: string;
}

export const VERTICAL_META: Record<string, VerticalMeta> = {
  restaurant: {
    icon: "🍽",
    primaryRevenueLabel: "Peak Hour Revenue",
    conversionLabel: "Lead Conversion Rate",
    avgValueLabel: "Avg Ticket",
    industryLabel: "Restaurant",
  },
  // Mirrors backend/app/knowledge/kbbq.py — labels intentionally identical
  // to restaurant; only icon + industryLabel differ for visual identification.
  // (KBBQ adapter와 일치 — 라벨 동일, 아이콘/산업명만 차별화)
  kbbq: {
    icon: "🥩",
    primaryRevenueLabel: "Peak Hour Revenue",
    conversionLabel: "Lead Conversion Rate",
    avgValueLabel: "Avg Ticket",
    industryLabel: "Korean BBQ",
  },
  home_services: {
    icon: "🔧",
    primaryRevenueLabel: "Field Time Revenue",
    conversionLabel: "Job Booking Rate",
    avgValueLabel: "Avg Job Value",
    industryLabel: "Home Services",
  },
  beauty: {
    icon: "💈",
    primaryRevenueLabel: "Booking Capture Revenue",
    conversionLabel: "Appointment Fill Rate",
    avgValueLabel: "Avg Service Value",
    industryLabel: "Beauty & Nail",
  },
  auto_repair: {
    icon: "🚗",
    primaryRevenueLabel: "Service Appointment Revenue",
    conversionLabel: "Estimate Conversion Rate",
    avgValueLabel: "Avg Repair Ticket",
    industryLabel: "Auto Repair",
  },
  // Restaurant-derivative verticals — labels mirror restaurant, only icon
  // + industryLabel differ. (식당계 vertical — 라벨 동일, 아이콘만 차별화)
  mexican: {
    icon: "🌮",
    primaryRevenueLabel: "Peak Hour Revenue",
    conversionLabel: "Lead Conversion Rate",
    avgValueLabel: "Avg Ticket",
    industryLabel: "Mexican",
  },
  pizza: {
    icon: "🍕",
    primaryRevenueLabel: "Peak Hour Revenue",
    conversionLabel: "Lead Conversion Rate",
    avgValueLabel: "Avg Ticket",
    industryLabel: "Pizza",
  },
};

export function getVerticalMeta(industry: string): VerticalMeta {
  return VERTICAL_META[industry] ?? VERTICAL_META.restaurant;
}
