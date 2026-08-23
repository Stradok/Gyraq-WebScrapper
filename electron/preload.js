const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('gyraq', {
  getLanUrl: () => ipcRenderer.invoke('get-lan-url'),
});
