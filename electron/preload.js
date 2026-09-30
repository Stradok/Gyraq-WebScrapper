const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('gyraq', {
  getLanUrl: () => ipcRenderer.invoke('get-lan-url'),
  chooseMode: (choice) => ipcRenderer.invoke('choose-mode', choice),
});
