import { create } from "zustand";
import { persist } from "zustand/middleware";

const BACKEND_URL = import.meta.env.VITE_WS_BACKEND_URL
  ? import.meta.env.VITE_WS_BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://").replace("/ws", "")
  : "http://localhost:8000";

const defaultAdminUser = {
  id: "test_admin",
  email: "admin@alita.ai",
  display_name: "Administrator",
  role: "admin",
};

export const useSessionStore = create(
  persist(
    (set, get) => ({
      user: defaultAdminUser,
      accessToken: "local_perpetual_admin_token",
      tier: "premium",

      setUser: (user) => set({ user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      setTier: (tier) => set({ tier }),
      clearSession: () => {
        set({ user: defaultAdminUser, accessToken: "local_perpetual_admin_token", tier: "premium" });
      },

      autoLoginDefaultAdmin: async () => {
        const state = get();
        if (state.user && state.accessToken) {
          return state.user;
        }
        try {
          const res = await fetch(`${BACKEND_URL}/auth/auto-login`);
          if (res.ok) {
            const data = await res.json();
            const userObj = {
              id: "test_admin",
              email: "admin@alita.ai",
              display_name: data.display_name || "Administrator",
              role: "admin",
            };
            set({
              user: userObj,
              accessToken: data.access_token,
              tier: data.tier || "premium",
            });
            return userObj;
          }
        } catch (e) {
          // Fallback offline mock for immediate UI hydration
          const mockUser = {
            id: "test_admin",
            email: "admin@alita.ai",
            display_name: "Administrator",
            role: "admin",
          };
          set({
            user: mockUser,
            accessToken: "local_perpetual_admin_token",
            tier: "premium",
          });
          return mockUser;
        }
      },
    }),
    {
      name: "alita-session", // localStorage key
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        tier: state.tier,
      }),
    }
  )
);