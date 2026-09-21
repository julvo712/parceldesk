export type Order = { order_id: string; product_name: string; sku?: string; delivered_at?: string; status?: string; image?: string; price?: number; quantity?: number };
export type Message = { role: 'user' | 'assistant'; content: string };
export type Proposal = { proposal_id: string; product_name?: string; arrival_date?: string; shipping_method?: string; status?: string; summary?: string; recipient?: string; replacement_id?: string; deadline_met?: boolean };
export type Conversation = { conversation_id: string; order_id: string; messages: Message[]; proposal?: Proposal | null; status?: string; scenario?: string; replacement_id?: string };
