import { writable } from 'svelte/store';

export const selectedChatId = writable(null);
export const chats = writable([]);
