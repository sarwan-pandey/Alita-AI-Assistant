import { create } from "zustand";
import { persist } from "zustand/middleware";

export const useSessionStore = create(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      tier: "free",

      setUser: (user) => set({ user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      setTier: (tier) => set({ tier }),
      clearSession: () => {
        set({ user: null, accessToken: null, tier: "free" });
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