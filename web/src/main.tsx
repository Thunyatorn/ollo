import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { SpacetimeDBProvider } from 'spacetimedb/react';
import { DbConnection } from './module_bindings';
import { STDB_DB, STDB_URI } from './config';
import { loadToken, saveToken } from './lib';
import App from './App';
import './styles.css';

const connectionBuilder = DbConnection.builder()
  .withUri(STDB_URI)
  .withDatabaseName(STDB_DB)
  .withToken(loadToken())
  .withAutomaticReconnect()
  .onConnect((_conn, _identity, token) => saveToken(token))
  .onConnectError((_ctx, error) => console.error('Spacetime connection error', error));

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <SpacetimeDBProvider connectionBuilder={connectionBuilder}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </SpacetimeDBProvider>
  </React.StrictMode>
);
