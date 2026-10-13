export interface PageInfo {
	id: string;
	title: string;
	url: string;
}

export interface TabInfo extends PageInfo {
	chrome_id: number;
	window_id: number;
	group_id: number;
	index: number;
}

export interface ProposedGroup {
	name: string;
	tab_ids: string[];
}

export interface Proposal {
	groups: ProposedGroup[];
}

export interface GroupingExample {
	name: string;
	pages: { title: string; url: string }[];
}

export interface PendingProposal extends Proposal {
	snapshot: TabInfo[];
	window_id: number;
}

export interface Connection {
	apiKey: string;
	model: string;
	remember: boolean;
	verifiedAt: string | null;
}

export interface ModelOption {
	id: string;
	name: string;
	note: string;
	created?: number;
}
