import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./app/App";
import "./app/styles.css";

const client=new QueryClient({
  defaultOptions:{
    queries:{staleTime:10000,retry:1,refetchOnWindowFocus:false},
    mutations:{retry:0},
  },
});
const root=document.getElementById("root");
if(!root) throw new Error("Root element not found");
createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter><App/></BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
