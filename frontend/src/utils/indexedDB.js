/**
 * IndexedDB helper — Offline conversation storage.
 *
 * Stores conversations locally in the browser so they persist
 * even when offline or after page refresh.
 *
 * Usage:
 *   import { dbSaveMessage, dbGetMessages, dbClearMessages } from "./indexedDB";
 *   await dbSaveMessage({ role: "user", content: "Hello", timestamp: Date.now() });
 *   const msgs = await dbGetMessages();
 */

const DB_NAME = "aura_db";
const DB_VERSION = 1;
const STORE_NAME = "messages";

function openDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                const store = db.createObjectStore(STORE_NAME, {
                    keyPath: "id",
                    autoIncrement: true,
                });
                store.createIndex("timestamp", "timestamp", { unique: false });
                store.createIndex("role", "role", { unique: false });
            }
        };

        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

/**
 * Save a message to IndexedDB.
 * @param {{ role: string, content: string, timestamp?: number }} msg
 */
export async function dbSaveMessage(msg) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        store.add({
            ...msg,
            timestamp: msg.timestamp || Date.now(),
        });
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
    });
}

/**
 * Get all messages, sorted by timestamp.
 * @param {number} [limit=100] — Max messages to retrieve
 * @returns {Promise<Array>}
 */
export async function dbGetMessages(limit = 100) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const store = tx.objectStore(STORE_NAME);
        const index = store.index("timestamp");
        const request = index.getAll(null, limit);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

/**
 * Clear all stored messages.
 */
export async function dbClearMessages() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        store.clear();
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
    });
}

/**
 * Get message count.
 * @returns {Promise<number>}
 */
export async function dbGetCount() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, "readonly");
        const store = tx.objectStore(STORE_NAME);
        const request = store.count();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}
