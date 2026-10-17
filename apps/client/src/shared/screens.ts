export type NavigationGroup = "home" | "assets" | "living" | "insurance" | "more";

export interface ScreenLink {
  to: string;
  label: string;
  description?: string;
}

export interface PlannedScreen {
  id: string;
  path: string;
  title: string;
  group: NavigationGroup;
  description: string;
  upcoming: string;
  parent: ScreenLink;
  links?: ScreenLink[];
  monthly?: boolean;
}
