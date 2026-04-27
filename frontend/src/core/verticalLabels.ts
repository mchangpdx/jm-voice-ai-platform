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
  home_services: {
    icon: "🔧",
    primaryRevenueLabel: "Field Time Revenue",
    conversionLabel: "Job Booking Rate",
    avgValueLabel: "Avg Job Value",
    industryLabel: "Home Services",
  },
};

export function getVerticalMeta(industry: string): VerticalMeta {
  return VERTICAL_META[industry] ?? VERTICAL_META.restaurant;
}
