import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import Shell from './Shell.jsx';
import './paper.css';

createRoot(document.getElementById('root')).render(<StrictMode><Shell /></StrictMode>);
