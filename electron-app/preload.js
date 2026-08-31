const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("scrapeApi", {
  setMode: (mode) => ipcRenderer.invoke("ui:set-mode", mode),
  openLogin: () => ipcRenderer.invoke("ui:open-login"),
  checkLogin: () => ipcRenderer.invoke("ui:check-login"),
  startScrape: (payload) => ipcRenderer.send("ui:start-scrape", payload),
  stopScrape: () => ipcRenderer.send("ui:stop-scrape"),
  exportExcel: (records, keywords) => ipcRenderer.invoke("ui:export-excel", { records, keywords }),
  onProgress: (callback) => {
    const handler = (_evt, data) => callback(data);
    ipcRenderer.on("scrape:progress", handler);
    return () => ipcRenderer.removeListener("scrape:progress", handler);
  },
  onViewUrl: (callback) => {
    const handler = (_evt, url) => callback(url);
    ipcRenderer.on("view:url", handler);
    return () => ipcRenderer.removeListener("view:url", handler);
  },
});
