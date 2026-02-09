"use client"

import React, { createContext, useContext, useEffect, useState, useCallback } from "react"
import { fetchCatalogData } from "./catalog-client"
import { transformAll, type CatalogData } from "./transformers"

type CatalogState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: CatalogData }

const CatalogContext = createContext<CatalogState>({ status: "loading" })
const CatalogRetryContext = createContext<() => void>(() => {})

export function CatalogProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<CatalogState>({ status: "loading" })

  const load = useCallback(async () => {
    setState({ status: "loading" })
    try {
      const { catalog, runs } = await fetchCatalogData()
      const data = transformAll(catalog, runs)
      setState({ status: "ready", data })
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Unknown error loading catalog",
      })
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <CatalogContext.Provider value={state}>
      <CatalogRetryContext.Provider value={load}>
        {children}
      </CatalogRetryContext.Provider>
    </CatalogContext.Provider>
  )
}

/** Raw state — use for loading/error checks. */
export function useCatalog(): CatalogState {
  return useContext(CatalogContext)
}

/** Returns a retry function to re-fetch catalog data. */
export function useCatalogRetry(): () => void {
  return useContext(CatalogRetryContext)
}

/**
 * Returns the transformed catalog data.
 * Only call this in components that render after the loading/error gate.
 * Throws if catalog is not ready.
 */
export function useCatalogData(): CatalogData {
  const state = useContext(CatalogContext)
  if (state.status !== "ready") {
    throw new Error("useCatalogData called before catalog is ready")
  }
  return state.data
}
