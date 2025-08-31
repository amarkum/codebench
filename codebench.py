# pylint: skip-file
# flake8: noqa
import csv
import gzip
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
import webbrowser
import zipfile
from datetime import datetime
from urllib.parse import urlparse
import requests

from flask import Flask, request, render_template_string, redirect, url_for, flash, session, send_file, jsonify
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.CRITICAL)

app = Flask(__name__)
app.secret_key = 'workbench_public_key'


# codebench Editor HTML template with modal problem selection and proper layout
CODEBENCH_EDIT_HTML = r"""
<!doctype html>
<html>
<head>
    <title>CodeBench</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        // Remove duplicates that were appearing later in the code
        let editorFullscreen = null;

        // Fullscreen toggle functions for each component
        function toggleProblemFullscreen() {
            const overlay = document.getElementById('problem-fullscreen');
            const content = document.getElementById('problem-fullscreen-content');
            const problemContent = document.getElementById('problem-statement').innerHTML;

            if (overlay.classList.contains('active')) {
                overlay.classList.remove('active');
            } else {
                content.innerHTML = problemContent;
                overlay.classList.add('active');
            }
        }

        function toggleEditorFullscreen() {
            const overlay = document.getElementById('editor-fullscreen');
            const container = document.getElementById('editor-fullscreen-container');

            if (overlay.classList.contains('active')) {
                overlay.classList.remove('active');
                // Move editor back
                if (editorFullscreen) {
                    document.getElementById('editor').appendChild(editorFullscreen.getContainerDomNode());
                    editorFullscreen = null;
                    if (window.monacoEditor) {
                        window.monacoEditor.layout();
                    }
                }
            } else {
                overlay.classList.add('active');
                container.innerHTML = '<div id="editor-fs" style="width: 100%; height: 100%;"></div>';

                // Create fullscreen editor
                if (window.monaco && window.monacoEditor) {
                    const value = window.monacoEditor.getValue();
                    const language = window.monacoEditor.getModel().getLanguageId();

                    editorFullscreen = monaco.editor.create(document.getElementById('editor-fs'), {
                        value: value,
                        language: language,
                        theme: document.body.classList.contains('theme-light') ? 'vs' : 'workbench-dark-theme',
                        automaticLayout: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        wordWrap: 'on',
                        fontSize: 16,
                        fontLigatures: true,
                        fontWeight: '400',
                        fontFamily: "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
                        tabSize: 4,
                        insertSpaces: true,
                        padding: { top: 0, bottom: 0 }
                    });

                    // Sync changes back
                    editorFullscreen.onDidChangeModelContent(() => {
                        window.monacoEditor.setValue(editorFullscreen.getValue());
                    });

                    // Sync language select
                    document.getElementById('language-select-fs').value = language;
                    document.getElementById('language-select-fs').onchange = function(e) {
                        const newLang = e.target.value;
                        monaco.editor.setModelLanguage(editorFullscreen.getModel(), newLang);
                        monaco.editor.setModelLanguage(window.monacoEditor.getModel(), newLang);
                        document.getElementById('language-select').value = newLang;
                    };

                    // Sync run button
                    document.getElementById('run-code-btn-fs').onclick = runCode;
                    document.getElementById('run-code-btn-fs').disabled = document.getElementById('run-code-btn').disabled;
                }
            }
        }

        function toggleTestResultsFullscreen() {
            const overlay = document.getElementById('test-results-fullscreen');
            const content = document.getElementById('test-results-fullscreen-content');
            const testContent = document.getElementById('test-results').innerHTML;

            if (overlay.classList.contains('active')) {
                overlay.classList.remove('active');
            } else {
                content.innerHTML = testContent;
                overlay.classList.add('active');
            }
        }
        // Apply saved theme ASAP to avoid flash (match RAW_EDIT_HTML) with migration from 'wb_theme'
        (function() {
            let saved = localStorage.getItem('workbench-theme');
            if (!saved) {
                const legacy = localStorage.getItem('wb_theme');
                if (legacy) {
                    saved = legacy === 'light' ? 'white' : 'dark';
                    localStorage.setItem('workbench-theme', saved);
                }
            }
            if (!saved) saved = 'dark';
            if (saved === 'white') {
                document.documentElement.classList.add('white-theme');
                document.body && document.body.classList.add('white-theme');
                const s = document.createElement('style'); s.textContent = 'html, body { background:#f8fafc!important; }'; document.head.appendChild(s);
            } else {
                document.documentElement.classList.add('dark-theme');
                document.body && document.body.classList.add('dark-theme');
                const s = document.createElement('style'); s.textContent = 'html, body { background:#1e293b!important; }'; document.head.appendChild(s);
            }
        })();
    </script>
    <script>
        window.MonacoEnvironment = {
          getWorkerUrl: function (moduleId, label) {
            return 'data:text/javascript;charset=utf-8,' + encodeURIComponent(
              "self.MonacoEnvironment={baseUrl:'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/'};importScripts('https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/base/worker/workerMain.js');"
            );
          }
        };
    </script>
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/editor/editor.main.css">
    <!-- Markdown rendering and sanitization -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
    <script>
        // Configure marked if available
        (function(){
            if (window.marked && window.marked.setOptions) {
                window.marked.setOptions({
                    gfm: true,
                    breaks: true
                });
            }
        })();
    </script>
    <style>
        * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important; box-sizing: border-box; }
        body, html { margin: 0; padding: 0; background-color: #0f172a !important; color: #e2e8f0 !important; height: 100%; overflow: hidden; }
        .btn { padding: 0.625rem 1.25rem; font-weight: 500; border-radius: 0; transition: all 0.2s ease; border: none; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 0.5rem; font-size: 0.875rem; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); height: 46px; }
        .btn:hover { transform: translateY(-1px); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06); }
        .btn:active { transform: translateY(0); box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); }
        .btn-primary { background-color: #6366f1; color: white !important; }
        .btn-primary:hover:not(:disabled) { background-color: #4f46e5; }
        .btn-success { background-color: #10b981; color: white !important; }
        .btn-success:hover:not(:disabled) { background-color: #059669; }
        .btn-ghost { background-color: transparent; color: #94a3b8 !important; border: 1px solid #475569; box-shadow: none; }
        .btn-ghost:hover:not(:disabled) { background-color: #334155; border-color: #64748b; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        /* Component fullscreen buttons */
        .btn-expand {
            width: 32px;
            height: 32px;
            padding: 0;
            background-color: transparent;
            color: #94a3b8;
            border: 1px solid #475569;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-expand:hover {
            background-color: #334155;
            color: #e2e8f0;
            border-color: #64748b;
        }
        .fullscreen-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #0f172a;
            z-index: 9999;
            display: none;
        }
        .fullscreen-overlay.active {
            display: flex;
            flex-direction: column;
        }
        .fullscreen-header {
            height: 60px;
            padding: 12px 20px;
            border-bottom: 1px solid #334155;
            background-color: #1e293b;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        /* Theme-aware native select to match RAW editor */
        .theme-select {
          border: 1px solid #475569;
          padding: 8px 12px;
          height: 36px;
          background-color: #334155;
          color: #e2e8f0;
          font-size: 14px;
          border-radius: 0;
          -webkit-appearance: menulist;
          -moz-appearance: menulist;
          appearance: auto;
        }
        .dark-theme .theme-select { background-color: #334155 !important; color: #e2e8f0 !important; border-color: #475569 !important; }
        body.white-theme .theme-select { background-color: #f8fafc !important; color: #1e293b !important; border-color: #e2e8f0 !important; }

        /* Monaco font + ligatures matching RAW */
        .monaco-editor, .monaco-editor *:not(.codicon) {
          font-family: 'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace !important;
          font-variant-ligatures: contextual;
        }
        .monaco-editor .codicon, .codicon { font: normal normal normal 16px/1 codicon !important; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }

        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.8); display: none; z-index: 1000; }
        .modal.show { display: flex; align-items: center; justify-content: center; }
        .modal-content { background-color: #1e293b; border-radius: 0; padding: 0; max-width: 900px; max-height: 80vh; width: 90%; overflow: hidden; border: 1px solid #334155; }
        .modal-header { padding: 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; background-color: #1e293b; }
        .modal-body { padding: 20px; max-height: 60vh; overflow-y: auto; }
        .tag { font-size: 12px; padding: 2px 8px; border-radius: 0; margin-right: 6px; margin-bottom: 4px; display: inline-block; }
        .tag-easy { background-color: rgba(16, 185, 129, 0.2); color: #10b981; }
        .tag-medium { background-color: rgba(245, 158, 11, 0.2); color: #f59e0b; }
        .tag-hard { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .tag-company { background-color: rgba(59, 130, 246, 0.2); color: #3b82f6; }
        .tag-category { background-color: rgba(139, 92, 246, 0.2); color: #8b5cf6; }
        .problem-card { padding: 16px; margin-bottom: 12px; border: 1px solid #475569; border-radius: 0; cursor: pointer; transition: all 0.2s ease; background-color: #0f172a; }
        .problem-card:hover { background-color: #1e293b; border-color: #64748b; }
        .problem-card.selected { border-color: #6366f1; background-color: #1e293b; }
        .filter-section { margin-bottom: 20px; padding: 15px; background-color: #0f172a; border-radius: 0; border: 1px solid #334155; }
        .test-case { background-color: #0f172a; border: 1px solid #334155; border-radius: 0; padding: 12px; margin-bottom: 8px; }
        .test-passed { border-color: #10b981; background-color: rgba(16, 185, 129, 0.1); }
        .test-failed { border-color: #ef4444; background-color: rgba(239, 68, 68, 0.1); }

        /* Custom Dropdown Styling */
        .custom-select {
            position: relative;
            display: inline-block;
        }
        .custom-select select {
            border-radius: 0 !important; 
            border: 1px solid #475569 !important; 
            background-color: #334155 !important; 
            color: #e2e8f0 !important; 
            font-family: inherit !important;
            padding: 8px 32px 8px 12px !important;
            font-size: 14px;
            height: 36px;
            width: 100%;
            cursor: pointer;
            -webkit-appearance: none;
            -moz-appearance: none;
            appearance: none;
            background-image: none;
        }
        .custom-select::after {
            content: '';
            position: absolute;
            top: 50%;
            right: 12px;
            transform: translateY(-50%);
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #e2e8f0;
            pointer-events: none;
        }
        .custom-select select:hover {
            border-color: #64748b;
        }
        .custom-select select:focus {
            outline: none;
            border-color: #6366f1;
            box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
        }
        .custom-select select option {
            background-color: #334155 !important;
            color: #e2e8f0 !important;
            padding: 8px 12px;
        }

        /* Remove native dropdown arrows completely */
        select::-ms-expand {
            display: none;
        }

        /* Markdown content styling for codebench-like appearance */
        .markdown-content {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        .markdown-content > :first-child {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }
        .markdown-content h1, .markdown-content h2, .markdown-content h3, .markdown-content h4 {
            color: #f1f5f9;
            margin: 6px 0 6px 0;
            font-weight: 600;
        }
        .markdown-content h1 { font-size: 20px; }
        .markdown-content h2 { font-size: 18px; }
        .markdown-content h3 { font-size: 16px; margin: 0 0 2px 0; }
        .markdown-content h4 { font-size: 15px; }
        .markdown-content h1:first-child, .markdown-content h2:first-child, .markdown-content h3:first-child { margin-top: 0; }

        .markdown-content p {
            margin: 12px 0;
            color: #cbd5e1;
            line-height: 1.7;
        }

        .markdown-content strong {
            color: #f1f5f9;
            font-weight: 600;
        }

        .markdown-content code {
            background-color: #334155;
            padding: 2px 6px;
            border-radius: 0;
            font-family: monospace;
            color: #e2e8f0;
            border: 1px solid #475569;
            font-size: 14px;
        }

        .markdown-content pre {
            background-color: #0f172a;
            padding: 8px 10px 6px 8px;
            border-radius: 0;
            border: 1px solid #334155;
            margin: 6px 0;
        }
        /* Tighten gap after Example headings -> first input block */
        .markdown-content h3 + pre,
        .markdown-content h4 + pre,
        .markdown-content p + pre,
        .markdown-content h3 + .test-case,
        .markdown-content h4 + .test-case,
        .markdown-content p + .test-case { margin-top: 0 !important; }
        .markdown-content h3 + pre,
        .markdown-content h4 + pre,
        .markdown-content p + pre { margin-top: 0 !important; }


        .markdown-content pre code {
            background-color: transparent;
            border: none;
            padding: 0;
            color: #e2e8f0;
            font-size: 13px;
            line-height: 1.34; /* tighter to reduce top visual gap */
            margin-top: 0; /* ensure no extra top gap inside code block */
            display: block; /* avoid inline baseline gap */
            white-space: pre-wrap;
        }

        .markdown-content ul, .markdown-content ol {
            margin: 12px 0;
            padding-left: 24px;
        }

        .markdown-content li {
            margin: 6px 0;
            color: #cbd5e1;
            line-height: 1.6;
        }

        .markdown-content blockquote {
            border-left: 4px solid #475569;
            margin: 16px 0;
            padding-left: 16px;
            color: #94a3b8;
            font-style: italic;
        }

        /* Draggable divider styling */
        .divider {
            width: 2px;
            background-color: #475569;
            cursor: col-resize;
            position: relative;
            transition: background-color 0.2s;
            flex-shrink: 0;
        }
        .divider:hover {
            background-color: #64748b;
        }
        .divider.dragging {
            background-color: #6366f1;
        }

        /* Vertical divider for code editor and test results */
        .vertical-divider {
            height: 8px; /* larger hit area */
            background-color: #475569;
            cursor: row-resize;
            position: relative;
            transition: background-color 0.2s;
            touch-action: none;
            z-index: 3; /* above Monaco container */
            flex-shrink: 0;
        }
        /* invisible larger handle to make grabbing easier */
        .vertical-divider::before {
            content: '';
            position: absolute;
            left: 0;
            right: 0;
            top: -6px;
            bottom: -6px;
            cursor: row-resize;
        }
        .vertical-divider:hover {
            background-color: #64748b;
        }
        .vertical-divider.dragging {
            background-color: #6366f1;
        }

        /* Light theme overrides (activated by adding class 'theme-light' on body) */
        body.theme-light { background-color: #ffffff !important; color: #0f172a !important; }
        body.theme-light .left-panel { background-color: #f8fafc; border-color: #e2e8f0; }
        body.theme-light .divider { background-color: #e2e8f0; }
        body.theme-light .vertical-divider { background-color: #e2e8f0; }
        body.theme-light #right-pane { background-color: #ffffff; }
        body.theme-light .problem-card { background-color: #ffffff; border-color: #e2e8f0; }
        body.theme-light .problem-card:hover { background-color: #f8fafc; border-color: #cbd5e1; }
        body.theme-light .filter-section { background-color: #ffffff; border-color: #e2e8f0; }
        body.theme-light .markdown-content p { color: #1f2937; }
        body.theme-light .markdown-content strong { color: #111827; }
        body.theme-light .markdown-content code { background-color: #f3f4f6; color: #111827; border-color: #e5e7eb; }
        body.theme-light .markdown-content pre { background-color: #f8fafc; border-color: #e5e7eb; }
        body.theme-light .test-case { background-color: #ffffff; border-color: #e5e7eb; }
        body.theme-light .modal-content { background-color: #ffffff; border-color: #e5e7eb; }
        body.theme-light .modal-header { background-color: #ffffff; border-color: #e5e7eb; }
        body.theme-light .btn-ghost { color: #334155 !important; border-color: #e5e7eb; }
        body.theme-light .btn-ghost:hover { background-color: #f3f4f6; border-color: #cbd5e1; }
        body.theme-light .tag-easy { background-color: rgba(16,185,129,0.12); color: #047857; }
        body.theme-light .tag-medium { background-color: rgba(245,158,11,0.12); color: #a16207; }
        body.theme-light .tag-hard { background-color: rgba(239,68,68,0.12); color: #b91c1c; }
    </style>
</head>
<body>
    <!-- Header -->
    <div id="top-header" style="padding: 15px 20px; border-bottom: 1px solid #334155; background-color: #1e293b; display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <a href="{{ url_for('home') }}" style="color: #e2e8f0; text-decoration: none; display: flex; align-items: center;">
                <h1 style="margin: 0; font-size: 30px; font-weight: 700; line-height: 1; color: #e2e8f0; display: inline-block;">🖥️&nbsp;CodeBench</h1>
            </a>
        </div>
        <div style="display: flex; gap: 10px;">
            <select id="theme-select" class="theme-select" title="Theme" style="height: 40px;">
                <option value="dark">Dark</option>
                <option value="white">Light</option>
            </select>
        </div>
    </div>

    <!-- Main Layout -->
    <div id="main-container" style="height: calc(100vh - 72px); display: flex; position: relative;">
        <!-- Left Pane: Problem Statement -->
        <div id="left-pane" class="left-panel" style="width: 45%; min-width: 300px; background-color: #1e293b; display: flex; flex-direction: column;">
            <div style="height: 60px; padding: 12px 20px; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                <h3 style="margin: 0; color: #e2e8f0; font-size: 16px; font-weight: 600;">Problem Statement</h3>
                <div style="display: flex; gap: 8px;">
                    <button id="open-problem-modal" class="btn btn-ghost" title="Select Problem" aria-label="Select Problem" onclick="openProblemModal()" style="height: 36px; line-height: 36px; padding: 0 10px;">📝</button>
                    <button class="btn-expand" title="Expand Problem Statement" onclick="toggleProblemFullscreen()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <polyline points="9 21 3 21 3 15"></polyline>
                            <line x1="21" y1="3" x2="14" y2="10"></line>
                            <line x1="3" y1="21" x2="10" y2="14"></line>
                        </svg>
                    </button>
                </div>
            </div>
            <div id="problem-statement" style="flex: 1; padding: 20px; overflow-y: auto;">
                <div style="height: 100%; display: flex; align-items: center; justify-content: center; text-align: center;">
                    <h2 style="margin: 0; color: #e2e8f0; font-size: 36px; font-weight: 400; letter-spacing: 0.2px;">No Problem Selected</h2>
                </div>
            </div>
        </div>

        <!-- Draggable Divider -->
        <div id="divider" class="divider"></div>

        <!-- Right Pane: Code Editor and Results -->
        <div id="right-pane" style="flex: 1; display: flex; flex-direction: column; min-width: 300px;">
            <!-- Top Right: Code Editor -->
            <div id="code-editor-section" style="flex: 1; display: flex; flex-direction: column; min-height: 200px;">
                <!-- Editor Controls -->
                <div id="editor-controls" style="height: 60px; padding: 12px 20px; border-bottom: 1px solid #334155; background-color: #1e293b; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; gap: 15px; align-items: center;">
                        <select id="language-select" class="theme-select" onchange="changeLanguage(this.value)" style="height: 36px;">
                            <option value="java">Java</option>
                            <option value="python">Python</option>
                        </select>
                        <button id="run-code-btn" class="btn btn-ghost" style="height: 36px; width: 36px; padding: 0; font-size: 14px; display: inline-flex; align-items: center; justify-content: center;" disabled>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polygon points="6 4 20 12 6 20 6 4"></polygon>
                            </svg>
                        </button>
                    </div>
                    <button class="btn-expand" title="Expand Code Editor" onclick="toggleEditorFullscreen()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <polyline points="9 21 3 21 3 15"></polyline>
                            <line x1="21" y1="3" x2="14" y2="10"></line>
                            <line x1="3" y1="21" x2="10" y2="14"></line>
                        </svg>
                    </button>
                </div>

                <!-- Monaco Editor -->
                <div id="editor" style="flex: 1; background-color: #1e1e1e; min-height: 200px;"></div>
            </div>

            <!-- Vertical Draggable Divider -->
            <div id="vertical-divider" class="vertical-divider"></div>

            <!-- Bottom Right: Test Results -->
            <div id="test-results-section" style="flex: 1; background-color: #0f172a; display: flex; flex-direction: column; min-height: 150px;">
                <div style="padding: 12px 20px; border-bottom: 1px solid #334155; background-color: #1e293b; display: flex; align-items: center; justify-content: space-between;">
                    <h3 style="margin: 0; color: #e2e8f0; font-size: 16px; font-weight: 600;">Test Results</h3>
                    <button class="btn-expand" title="Expand Test Results" onclick="toggleTestResultsFullscreen()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <polyline points="9 21 3 21 3 15"></polyline>
                            <line x1="21" y1="3" x2="14" y2="10"></line>
                            <line x1="3" y1="21" x2="10" y2="14"></line>
                        </svg>
                    </button>
                </div>
                <div id="test-results" style="flex: 1; padding: 20px; overflow-y: auto;">
                    <div style="text-align: center; color: #94a3b8; padding: 40px 20px;">
                        <p>Run your code to see test results</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Fullscreen Overlays for each component -->
    <div id="problem-fullscreen" class="fullscreen-overlay">
        <div class="fullscreen-header">
            <h3 style="margin: 0; color: #e2e8f0; font-size: 18px; font-weight: 600;">Problem Statement</h3>
            <button class="btn-expand" onclick="toggleProblemFullscreen()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="8 3 3 3 3 8"></polyline>
                    <polyline points="21 8 21 3 16 3"></polyline>
                    <polyline points="16 21 21 21 21 16"></polyline>
                    <polyline points="3 16 3 21 8 21"></polyline>
                </svg>
            </button>
        </div>
        <div id="problem-fullscreen-content" style="flex: 1; padding: 20px; overflow-y: auto; background-color: #1e293b;">
        </div>
    </div>

    <div id="editor-fullscreen" class="fullscreen-overlay">
        <div class="fullscreen-header">
            <div style="display: flex; gap: 15px; align-items: center;">
                <select id="language-select-fs" class="theme-select" style="height: 36px;">
                    <option value="java">Java</option>
                    <option value="python">Python</option>
                </select>
                <button id="run-code-btn-fs" class="btn btn-ghost" style="height: 36px; width: 36px; padding: 0;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="6 4 20 12 6 20 6 4"></polygon>
                    </svg>
                </button>
            </div>
            <button class="btn-expand" onclick="toggleEditorFullscreen()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="8 3 3 3 3 8"></polyline>
                    <polyline points="21 8 21 3 16 3"></polyline>
                    <polyline points="16 21 21 21 21 16"></polyline>
                    <polyline points="3 16 3 21 8 21"></polyline>
                </svg>
            </button>
        </div>
        <div id="editor-fullscreen-container" style="flex: 1;">
        </div>
    </div>

    <div id="test-results-fullscreen" class="fullscreen-overlay">
        <div class="fullscreen-header">
            <h3 style="margin: 0; color: #e2e8f0; font-size: 18px; font-weight: 600;">Test Results</h3>
            <button class="btn-expand" onclick="toggleTestResultsFullscreen()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="8 3 3 3 3 8"></polyline>
                    <polyline points="21 8 21 3 16 3"></polyline>
                    <polyline points="16 21 21 21 21 16"></polyline>
                    <polyline points="3 16 3 21 8 21"></polyline>
                </svg>
            </button>
        </div>
        <div id="test-results-fullscreen-content" style="flex: 1; padding: 20px; overflow-y: auto; background-color: #0f172a;">
        </div>
    </div>

    <!-- Problem Selection Modal -->
    <div id="problem-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 style="margin: 0; color: #e2e8f0; font-size: 20px; font-weight: 600;">Select a Problem</h2>
                <button onclick="closeProblemModal()" class="btn btn-ghost" style="padding: 8px;">✕</button>
            </div>
            <div class="modal-body">
                <!-- Filters -->
                <div class="filter-section">
                    <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                        <div>
                            <label style="color: #cbd5e1; font-size: 14px; margin-right: 8px; margin-bottom: 4px; display: block;">Difficulty:</label>
                            <div class="custom-select" style="min-width: 120px;">
                                <select id="difficulty-filter">
                                    <option value="">All</option>
                                    <option value="Easy">Easy</option>
                                    <option value="Medium">Medium</option>
                                    <option value="Hard">Hard</option>
                                </select>
                            </div>
                        </div>
                        <div>
                            <label style="color: #cbd5e1; font-size: 14px; margin-right: 8px; margin-bottom: 4px; display: block;">Company:</label>
                            <div class="custom-select" style="min-width: 120px;">
                                <select id="company-filter">
                                    <option value="">All</option>
                                    <option value="Google">Google</option>
                                    <option value="Amazon">Amazon</option>
                                    <option value="Microsoft">Microsoft</option>
                                    <option value="Top-50">Top-50</option>
                                </select>
                            </div>
                        </div>
                        <div>
                            <label style="color: #cbd5e1; font-size: 14px; margin-right: 8px; margin-bottom: 4px; display: block;">Sort:</label>
                            <div class="custom-select" style="min-width: 120px;">
                                <select id="sort-filter">
                                    <option value="id">Problem ID</option>
                                    <option value="difficulty">Difficulty</option>
                                    <option value="title">Title</option>
                                </select>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Problem List -->
                <div id="modal-problem-list">
                    <div style="text-align: center; color: #94a3b8; padding: 20px;">Loading problems...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Global variables
        let editor = null;
        let currentProblem = null;
        let allProblems = [];
        let filteredProblems = [];
        let isFullscreen = false;

        // Fullscreen toggle function
        function toggleFullscreen() {
            if (!isFullscreen) {
                if (document.documentElement.requestFullscreen) {
                    document.documentElement.requestFullscreen();
                } else if (document.documentElement.webkitRequestFullscreen) {
                    document.documentElement.webkitRequestFullscreen();
                } else if (document.documentElement.mozRequestFullScreen) {
                    document.documentElement.mozRequestFullScreen();
                } else if (document.documentElement.msRequestFullscreen) {
                    document.documentElement.msRequestFullscreen();
                }
                isFullscreen = true;
                updateFullscreenIcon(true);
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                } else if (document.mozCancelFullScreen) {
                    document.mozCancelFullScreen();
                } else if (document.msExitFullscreen) {
                    document.msExitFullscreen();
                }
                isFullscreen = false;
                updateFullscreenIcon(false);
            }
        }

        function updateFullscreenIcon(isFullscreen) {
            const icon = document.getElementById('fullscreen-icon');
            if (isFullscreen) {
                icon.innerHTML = `
                    <polyline points="8 3 3 3 3 8"></polyline>
                    <polyline points="21 8 21 3 16 3"></polyline>
                    <polyline points="16 21 21 21 21 16"></polyline>
                    <polyline points="3 16 3 21 8 21"></polyline>
                `;
            } else {
                icon.innerHTML = `
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <polyline points="9 21 3 21 3 15"></polyline>
                    <line x1="21" y1="3" x2="14" y2="10"></line>
                    <line x1="3" y1="21" x2="10" y2="14"></line>
                `;
            }
        }

        // Listen for fullscreen changes
        document.addEventListener('fullscreenchange', () => {
            isFullscreen = !!document.fullscreenElement;
            updateFullscreenIcon(isFullscreen);
        });

        // Normalize YAML-indented Markdown (remove common leading spaces, fix fenced code)
        function normalizeYamlMarkdown(md) {
            if (!md) return md;
            const lines = md.replace(/\t/g, '    ').split('\n');
            // compute common leading indentation (ignore empty lines)
            let minIndent = Infinity;
            for (const ln of lines) {
                if (ln.trim().length === 0) continue;
                const m = ln.match(/^\s*/)[0].length;
                if (m < minIndent) minIndent = m;
            }
            if (!isFinite(minIndent)) minIndent = 0;
            const out = lines.map(l => l.slice(Math.min(minIndent, l.match(/^\s*/)[0].length)));
            // additionally, ensure fenced lines start at column 0
            let joined = out.map(l => l.replace(/^\s*```/, '```')).join('\n');
            // trim leading blank lines to avoid unwanted top gap
            joined = joined.replace(/^(\s*\n)+/, '');
            return joined;
        }

        // Remove a duplicate leading Markdown heading (we render title separately)
        function stripHeadingFromMarkdown(md, title) {
            if (!md) return md;
            const firstLineEnd = md.indexOf('\n');
            const firstLine = (firstLineEnd === -1 ? md : md.slice(0, firstLineEnd)).trim();
            const titleNorm = (title || '').toLowerCase().replace(/^\d+\.?\s*/, '');
            const lineNorm = firstLine.replace(/^#+\s*/, '').toLowerCase();
            if (/^#/.test(firstLine) && (titleNorm && lineNorm.includes(titleNorm))) {
                const rest = (firstLineEnd === -1 ? '' : md.slice(firstLineEnd + 1));
                return rest.replace(/^\s+/, '');
            }
            return md;
        }

        // Safe Markdown render helper with fallbacks
        function renderMarkdownSafe(md) {
            try {
                const markedApi = (window.marked && (window.marked.parse || window.marked)) ? window.marked : null;
                let html = md;
                if (markedApi) {
                    html = (window.marked.parse ? window.marked.parse(md) : window.marked(md));
                } else {
                    // Fallback renderer: basic Markdown to HTML
                    console.warn('marked.js not available, using basic fallback renderer');
                    // Escape HTML first
                    html = md
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;');
                    // Code fences ```...```
                    html = html.replace(/```([\s\S]*?)```/g, function(_, code){
                        return '<pre><code>' + code.replace(/\n/g, '\n') + '</code></pre>';
                    });
                    // Inline code `code`
                    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
                    // Bold and italics
                    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
                    // Headings ####, ###, ##, #
                    html = html.replace(/^####\s+(.*)$/gm, '<h4>$1</h4>')
                               .replace(/^###\s+(.*)$/gm, '<h3>$1</h3>')
                               .replace(/^##\s+(.*)$/gm, '<h2>$1</h2>')
                               .replace(/^#\s+(.*)$/gm, '<h1>$1</h1>');
                    // Blockquotes
                    html = html.replace(/^>\s?(.*)$/gm, '<blockquote>$1</blockquote>');
                    // Unordered lists
                    html = html.replace(/^(?:- |\* )(.*)$/gm, '<li>$1</li>');
                    html = html.replace(/(<li>.*<\/li>)(\n<li>)/g, '$1$2');
                    html = html.replace(/(?:\n)?(<li>[\s\S]*?<\/li>)+/g, function(match){
                        return '<ul>' + match.replace(/\n/g, '') + '</ul>';
                    });
                    // Paragraphs and line breaks
                    html = html.replace(/\n\n+/g, '</p><p>');
                    html = '<p>' + html.replace(/\n/g, '<br>') + '</p>';
                }
                if (window.DOMPurify && window.DOMPurify.sanitize) {
                    return window.DOMPurify.sanitize(html);
                }
                return html;
            } catch (e) {
                try {
                    return md.replace(/\n/g, '<br>');
                } catch (_) {
                    return md;
                }
            }
        }

        // Initialize Monaco Editor - exact copy from RAW_EDIT_HTML
        function applyDarkTheme() {
          const themeId = 'workbench-dark-theme';
          try {
            monaco.editor.defineTheme(themeId, {
              base: 'vs-dark', inherit: true, rules: [],
              colors: {
                'editor.background': '#1e293b',
                'editor.foreground': '#e2e8f0',
                'editorGutter.background': '#1e293b',
                'editorLineNumber.foreground': '#94a3b8',
                'editorLineNumber.activeForeground': '#ffffff',
                'editor.selectionBackground': '#334155',
                'editorIndentGuide.background': '#334155',
                'editorIndentGuide.activeBackground': '#64748b'
              }
            });
          } catch (e) {}
          monaco.editor.setTheme(themeId);
          return themeId;
        }

        // Load Monaco
        require.config({ paths: { 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], function() {
          const themeId = applyDarkTheme();
          const initialLang = (document.getElementById('language-select') && document.getElementById('language-select').value) || 'java';
          window.monacoEditor = monaco.editor.create(document.getElementById('editor'), {
            value: '// Select a problem to start coding',
            language: initialLang,
            theme: 'workbench-dark-theme',
            automaticLayout: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            fontSize: 16,
            fontLigatures: true,
            fontWeight: '400',
            fontFamily: "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
            tabSize: 4,
            insertSpaces: true,
            renderWhitespace: 'boundary',
            cursorBlinking: 'solid',
            cursorStyle: 'line',
            smoothScrolling: true,
            mouseWheelZoom: false,
            roundedSelection: false,
            renderLineHighlight: 'gutter',
            lineDecorationsWidth: 16,
            glyphMargin: true,
            folding: true,
            foldingHighlight: true,
            showFoldingControls: 'always',
            padding: { top: 0, bottom: 0 } // Remove top padding
          });

          // Ensure Monaco editor is positioned correctly and starts invisible
          const monacoContainer = window.monacoEditor.getContainerDomNode();
          monacoContainer.style.position = 'relative';
          monacoContainer.style.zIndex = '2';
          monacoContainer.style.opacity = '0';
          monacoContainer.style.transition = 'opacity 0.3s ease';

          // Fade in Monaco editor
          setTimeout(() => {
            monacoContainer.style.opacity = '1';
          }, 50);
          window.monacoEditor.updateOptions({ fontFamily: "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace"});
          try { monaco.editor.remeasureFonts(); } catch(e) {}

          // Load problems
          loadProblems();
        });

        // Language change handler
        function changeLanguage(lang) {
            if (window.monacoEditor) {
                monaco.editor.setModelLanguage(window.monacoEditor.getModel(), lang);
            }
        }

        // Initialize theme from localStorage
        let savedTheme = localStorage.getItem('workbench-theme');
        if (!savedTheme) {
            const legacy = localStorage.getItem('wb_theme');
            if (legacy) {
                savedTheme = legacy === 'light' ? 'white' : 'dark';
                localStorage.setItem('workbench-theme', savedTheme);
            }
        }
        if (!savedTheme) savedTheme = 'dark';
        applyTheme(savedTheme);
        const themeSelect = document.getElementById('theme-select');
        if (themeSelect) {
            themeSelect.value = savedTheme;
            themeSelect.addEventListener('change', (e) => {
                applyTheme(e.target.value);
            });
        }

        function applyTheme(theme) {
            const body = document.body;
            const root = document.documentElement;
            if (theme === 'white') {
                // toggle root/body classes
                root.classList.remove('dark-theme');
                root.classList.add('white-theme');
                body.classList.remove('dark-theme');
                body.classList.add('theme-light');
                body.classList.add('white-theme');
                try { if (window.monaco && window.monaco.editor) { monaco.editor.setTheme('vs'); } } catch (e) {}
                // adjust header bars for light theme
                const top = document.getElementById('top-header');
                const controls = document.getElementById('editor-controls');
                if (top) { top.style.backgroundColor = '#f8fafc'; top.style.borderBottomColor = '#e5e7eb'; }
                if (controls) { controls.style.backgroundColor = '#f8fafc'; controls.style.borderBottomColor = '#e5e7eb'; }
            } else {
                // toggle root/body classes
                root.classList.remove('white-theme');
                root.classList.add('dark-theme');
                body.classList.remove('white-theme');
                body.classList.remove('theme-light');
                body.classList.add('dark-theme');
                try { if (window.monaco && window.monaco.editor) { monaco.editor.setTheme('workbench-dark-theme'); } } catch (e) {}
                const top = document.getElementById('top-header');
                const controls = document.getElementById('editor-controls');
                if (top) { top.style.backgroundColor = '#1e293b'; top.style.borderBottomColor = '#334155'; }
                if (controls) { controls.style.backgroundColor = '#1e293b'; controls.style.borderBottomColor = '#334155'; }
            }
            localStorage.setItem('workbench-theme', theme);
        }

        function loadProblems() {
            fetch('/codebench/problems')
                .then(response => response.json())
                .then(data => {
                    allProblems = data;
                    filteredProblems = [...allProblems];
                    displayModalProblems();
                })
                .catch(error => {
                    console.error('Error loading problems:', error);
                });
        }

        function openProblemModal() {
            document.getElementById('problem-modal').classList.add('show');
        }

        function closeProblemModal() {
            document.getElementById('problem-modal').classList.remove('show');
        }

        function displayModalProblems() {
            const container = document.getElementById('modal-problem-list');
            container.innerHTML = '';

            filteredProblems.forEach(problem => {
                const card = document.createElement('div');
                card.className = 'problem-card';
                card.onclick = () => selectProblem(problem);

                const difficultyClass = problem.difficulty.toLowerCase();
                const tagsHtml = problem.tags.map(tag => {
                    let tagClass = 'tag-category';
                    if (['Easy', 'Medium', 'Hard'].includes(tag)) tagClass = `tag-${tag.toLowerCase()}`;
                    else if (['Google', 'Amazon', 'Microsoft', 'Apple', 'Facebook'].includes(tag)) tagClass = 'tag-company';
                    return `<span class="tag ${tagClass}">${tag}</span>`;
                }).join('');

                // Create a clean preview from Markdown: strip markdown tokens and collapse whitespace
                const previewText = normalizeYamlMarkdown(problem.description)
                    .replace(/```[\s\S]*?```/g, ' ')      // remove code fences content
                    .replace(/`([^`]+)`/g, '$1')            // inline code
                    .replace(/\*\*(.*?)\*\*/g, '$1')     // bold
                    .replace(/\*(.*?)\*/g, '$1')          // italics
                    .replace(/^#+\s+/gm, '')               // headings
                    .replace(/\[(.*?)\]\([^)]*\)/g, '$1')// links
                    .replace(/>\s?/g, '')                  // blockquote markers
                    .replace(/[-*]\s+/g, '')               // list bullets
                    .replace(/\n+/g, ' ')                  // newlines -> space
                    .trim()
                    .substring(0, 140);

                card.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
                        <h4 style="margin: 0; color: #e2e8f0; font-size: 16px; font-weight: 600;">${problem.id}. ${problem.title}</h4>
                        <span class="tag tag-${difficultyClass}">${problem.difficulty}</span>
                    </div>
                    <div style="margin-bottom: 8px;">${tagsHtml}</div>
                    <p style="margin: 0; color: #94a3b8; font-size: 14px; line-height: 1.4;">${previewText}...</p>
                `;

                container.appendChild(card);
            });
        }

        function selectProblem(problem) {
            currentProblem = problem;
            closeProblemModal();

            // Update problem statement
            const statement = document.getElementById('problem-statement');
            const difficultyClass = problem.difficulty.toLowerCase();
            const tagsHtml = problem.tags.map(tag => {
                let tagClass = 'tag-category';
                if (['Easy', 'Medium', 'Hard'].includes(tag)) tagClass = `tag-${tag.toLowerCase()}`;
                else if (['Google', 'Amazon', 'Microsoft', 'Apple', 'Facebook'].includes(tag)) tagClass = 'tag-company';
                return `<span class="tag ${tagClass}">${tag}</span>`;
            }).join('');

            // Normalize YAML indentation then render Markdown safely (with fallbacks)
            let normalizedMd = normalizeYamlMarkdown(problem.description);
            normalizedMd = stripHeadingFromMarkdown(normalizedMd, problem.title);
            let markedHtml = renderMarkdownSafe(normalizedMd);
            // Remove any empty leading <p></p> that may be produced by Markdown parser
            markedHtml = markedHtml.replace(/^\s*(<p>\s*<\/p>)+/i, '');
            // Trim leading blank line inside code blocks and trailing blank line before closing
            // This removes the first extra newline that renders as an empty line before "Input:" etc.
            markedHtml = markedHtml
                .replace(/(<pre>\s*<code[^>]*>)\s+/g, '$1')
                .replace(/\s+<\/code>\s*<\/pre>/g, '</code></pre>');

            statement.innerHTML = `
                <div style="margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <h2 style="margin: 0; color: #e2e8f0; font-size: 22px; font-weight: 600;">${problem.id}. ${problem.title}</h2>
                        <span class="tag tag-${difficultyClass}">${problem.difficulty}</span>
                    </div>
                    <div style="margin-bottom: 15px;">${tagsHtml}</div>
                </div>
                <div class="markdown-content">
                    ${markedHtml}
                </div>
            `;

            // After injection, remove any leading/trailing blank lines inside code blocks
            try {
                const container = document.getElementById('problem-statement');
                const mdRoot = container.querySelector('.markdown-content');
                container.querySelectorAll('pre code').forEach((codeEl) => {
                    const text = codeEl.textContent || '';
                    let content = text
                        .replace(/^\s*\n+/, '')   // leading blank lines
                        .replace(/\n+\s*$/, ''); // trailing blank lines

                    // If this looks like an I/O example block, normalize and remove blank-only lines
                    if (/\bInput:\b|\bOutput:\b|\bExplanation:\b/.test(content)) {
                        // Normalize NBSP to regular spaces
                        content = content.replace(/\u00a0/g, ' ');
                        // Collapse 2+ newlines into a single newline
                        content = content.replace(/(?:\r?\n){2,}/g, '\n');
                        // Remove blank-only lines and trailing spaces per line
                        const lines = content.split(/\r?\n/);
                        let cleaned = lines
                            .map(l => l
                                // strip trailing spaces
                                .replace(/\s+$/, '')
                                // strip zero-width and exotic leading spaces
                                .replace(/^[\u200B\u2000-\u200A\u202F\u205F\u3000\ufeff]+/, '')
                            )
                            .filter(l => l.trim() !== '');

                        // Dedent: remove common leading indentation across non-empty lines
                        let minIndent = Infinity;
                        cleaned.forEach(l => {
                            if (l.trim() === '') return;
                            const m = l.match(/^(\s+)/);
                            const n = m ? m[1].length : 0;
                            if (n < minIndent) minIndent = n;
                        });
                        if (minIndent !== Infinity && minIndent > 0) {
                            const re = new RegExp('^\\s{0,' + minIndent + '}');
                            cleaned = cleaned.map(l => l.replace(re, ''));
                        }

                        // Ensure labels start at column 0
                        cleaned = cleaned.map(l => l.replace(/^\s*(Input:|Output:|Explanation:)/, '$1'));

                        content = cleaned.join('\n');
                    }

                    if (content !== text) codeEl.textContent = content;
                });

                // Remove empty paragraphs between headings (Example X:) and code blocks
                if (mdRoot) {
                    mdRoot.querySelectorAll('h3, h4').forEach((h) => {
                        let next = h.nextElementSibling;
                        while (
                            next &&
                            next.tagName === 'P' &&
                            (
                                (next.textContent || '').replace(/\u00a0/g, ' ').trim() === '' ||
                                next.innerHTML.trim().toLowerCase() === '<br>'
                            )
                        ) {
                            const removeMe = next;
                            next = next.nextElementSibling;
                            removeMe.remove();
                        }
                    });
                }
            } catch (err) { /* no-op */ }

            // Update editor
            const language = document.getElementById('language-select').value;
            const template = problem.templates[language] || '';

            if (window.monacoEditor) {
                monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);
                window.monacoEditor.setValue(template);
                window.monacoEditor.updateOptions({ readOnly: false });
                document.getElementById('run-code-btn').disabled = false;
            }
        }

        function runCode() {
            if (!window.monacoEditor || !currentProblem) return;

            const code = window.monacoEditor.getValue();
            const language = document.getElementById('language-select').value;

            if (!code.trim()) {
                alert('Please write some code first!');
                return;
            }

            const runBtn = document.getElementById('run-code-btn');
            const resultsContainer = document.getElementById('test-results');

            runBtn.disabled = true;
            runBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="32"><animate attributeName="stroke-dashoffset" dur="1.5s" repeatCount="indefinite" from="32" to="0"/></circle></svg>';
            resultsContainer.innerHTML = '<div style="text-align: center; color: #f59e0b; padding: 20px;">Executing test cases...</div>';

            fetch('/codebench/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code: code,
                    language: language,
                    problem_id: currentProblem.id
                })
            })
            .then(response => response.json())
            .then(data => {
                displayTestResults(data);
            })
            .catch(error => {
                console.error('Error:', error);
                resultsContainer.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">❌ Failed to run tests</div>';
            })
            .finally(() => {
                runBtn.disabled = false;
                runBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>';
            });
        }

        function displayTestResults(results) {
            const container = document.getElementById('test-results');

            if (results.error) {
                container.innerHTML = `
                    <div style="color: #ef4444; padding: 20px; text-align: center;">
                        <h4 style="margin: 0 0 10px 0; color: #ef4444;">❌ Compilation Error</h4>
                        <pre style="background-color: #1e293b; padding: 15px; border: 1px solid #334155; overflow-x: auto; color: #fca5a5; font-family: monospace; font-size: 13px; margin: 0; text-align: left;">${results.error}</pre>
                    </div>
                `;
                // Also update fullscreen if active
                const fsContent = document.getElementById('test-results-fullscreen-content');
                if (document.getElementById('test-results-fullscreen').classList.contains('active')) {
                    fsContent.innerHTML = container.innerHTML;
                }
                return;
            }

            const passed = results.passed || 0;
            const total = results.total || 0;
            const testCases = results.test_cases || [];
            const failed = total - passed;

            let html = `
                <div style="margin-bottom: 20px; padding: 15px; background-color: #1e293b; border: 1px solid #334155;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <h4 style="margin: 0; color: #e2e8f0; font-size: 16px;">Test Results</h4>
                        <div style="display: flex; gap: 10px; align-items: center;">
                            <span style="color: #10b981; font-weight: 600;">✓ ${passed} passed</span>
                            <span style="color: #ef4444; font-weight: 600;">✗ ${failed} failed</span>
                            <span style="color: #64748b;">Total: ${total}</span>
                        </div>
                    </div>
                    <div style="width: 100%; height: 8px; background-color: #334155; overflow: hidden;">
                        <div style="width: ${total > 0 ? (passed / total) * 100 : 0}%; height: 100%; background-color: #10b981; transition: width 0.3s ease;"></div>
                    </div>
                </div>
            `;

            testCases.forEach((testCase, index) => {
                const status = testCase.passed ? 'test-passed' : 'test-failed';
                const statusIcon = testCase.passed ? '✓' : '✗';
                const statusColor = testCase.passed ? '#10b981' : '#ef4444';

                html += `
                    <div class="test-case ${status}">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <strong style="color: #e2e8f0; font-size: 14px;">Test Case ${index + 1}</strong>
                            <span style="color: ${statusColor}; font-weight: 600; font-size: 13px;">${statusIcon} ${testCase.passed ? 'PASSED' : 'FAILED'}</span>
                        </div>
                        <div style="margin-bottom: 8px;">
                            <span style="color: #94a3b8; font-size: 13px;">Input: </span>
                            <span style="color: #e2e8f0; font-family: monospace; font-size: 13px;">${JSON.stringify(testCase.input)}</span>
                        </div>
                        <div style="margin-bottom: 8px;">
                            <span style="color: #94a3b8; font-size: 13px;">Expected: </span>
                            <span style="color: #e2e8f0; font-family: monospace; font-size: 13px;">${JSON.stringify(testCase.expected)}</span>
                        </div>
                        ${!testCase.passed ? `
                        <div style="margin-bottom: 8px;">
                            <span style="color: #94a3b8; font-size: 13px;">Output: </span>
                            <span style="color: #fca5a5; font-family: monospace; font-size: 13px;">${JSON.stringify(testCase.actual)}</span>
                        </div>
                        ` : ''}
                        ${testCase.error ? `
                        <div style="margin-top: 8px; padding: 8px; background-color: #1e293b; border: 1px solid #334155;">
                            <span style="color: #ef4444; font-size: 13px; font-weight: 600;">Error: </span>
                            <span style="color: #fca5a5; font-family: monospace; font-size: 12px;">${testCase.error}</span>
                        </div>
                        ` : ''}
                    </div>
                `;
            });

            container.innerHTML = html;

            // Also update fullscreen if active
            const fsContent = document.getElementById('test-results-fullscreen-content');
            if (document.getElementById('test-results-fullscreen').classList.contains('active')) {
                fsContent.innerHTML = html;
            }
        }

        // Event listeners
        (function(){
            const modalBtn = document.getElementById('open-problem-modal');
            if (modalBtn) modalBtn.onclick = openProblemModal;
        })();
        document.getElementById('run-code-btn').onclick = runCode;

        document.getElementById('language-select').onchange = function(e) {
            if (currentProblem && window.monacoEditor) {
                const language = e.target.value;
                const template = currentProblem.templates[language] || '';
                monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);
                window.monacoEditor.setValue(template);
            }
        };

        // Filter functionality
        function applyFilters() {
            const difficulty = document.getElementById('difficulty-filter').value;
            const company = document.getElementById('company-filter').value;
            const sort = document.getElementById('sort-filter').value;

            filteredProblems = allProblems.filter(problem => {
                if (difficulty && problem.difficulty !== difficulty) return false;
                if (company && !problem.tags.includes(company)) return false;
                return true;
            });

            // Sort
            filteredProblems.sort((a, b) => {
                if (sort === 'difficulty') {
                    const order = { 'Easy': 1, 'Medium': 2, 'Hard': 3 };
                    return order[a.difficulty] - order[b.difficulty];
                } else if (sort === 'title') {
                    return a.title.localeCompare(b.title);
                } else {
                    return a.id - b.id;
                }
            });

            displayModalProblems();
        }

        document.getElementById('difficulty-filter').onchange = applyFilters;
        document.getElementById('company-filter').onchange = applyFilters;
        document.getElementById('sort-filter').onchange = applyFilters;

        // Close modal on outside click
        document.getElementById('problem-modal').onclick = function(e) {
            if (e.target === this) closeProblemModal();
        };

        // Draggable divider functionality
        let isDragging = false;
        let isVerticalDragging = false;
        let startX, startY, startLeftWidth, startCodeHeight;

        const divider = document.getElementById('divider');
        const leftPane = document.getElementById('left-pane');
        const rightPane = document.getElementById('right-pane');

        const verticalDivider = document.getElementById('vertical-divider');
        const codeEditorSection = document.getElementById('code-editor-section');
        const testResultsSection = document.getElementById('test-results-section');

        // Horizontal divider (left/right panes)
        divider.addEventListener('mousedown', function(e) {
            isDragging = true;
            startX = e.clientX;
            startLeftWidth = leftPane.offsetWidth;

            divider.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        // Vertical divider (code editor/test results) - FIXED VERSION
        verticalDivider.addEventListener('mousedown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            isVerticalDragging = true;
            startY = e.clientY;

            // Get the actual heights at drag start
            const rightPaneRect = rightPane.getBoundingClientRect();
            const codeRect = codeEditorSection.getBoundingClientRect();

            startCodeHeight = codeRect.height;

            verticalDivider.classList.add('dragging');
            document.body.style.cursor = 'row-resize';
            document.body.style.userSelect = 'none';
        });

        // Add touch support for mobile
        divider.addEventListener('touchstart', function(e) {
            const touch = e.touches[0];
            isDragging = true;
            startX = touch.clientX;
            startLeftWidth = leftPane.offsetWidth;
            divider.classList.add('dragging');
            e.preventDefault();
        });

        verticalDivider.addEventListener('touchstart', function(e) {
            const touch = e.touches[0];
            e.preventDefault();
            e.stopPropagation();
            isVerticalDragging = true;
            startY = touch.clientY;
            const codeRect = codeEditorSection.getBoundingClientRect();
            startCodeHeight = codeRect.height;
            verticalDivider.classList.add('dragging');
        });

        document.addEventListener('mousemove', function(e) {
            // Handle horizontal dragging
            if (isDragging) {
                const deltaX = e.clientX - startX;
                const totalWidth = leftPane.parentElement.offsetWidth;
                let newWidthPx = startLeftWidth + deltaX;
                let pct = newWidthPx / totalWidth;
                pct = Math.max(0.15, Math.min(0.85, pct));
                leftPane.style.width = (pct * 100).toFixed(2) + '%';

                if (window.monacoEditor) {
                    requestAnimationFrame(() => window.monacoEditor.layout());
                }
            }

            // Handle vertical dragging - FIXED VERSION
            if (isVerticalDragging) {
                e.preventDefault();
                const deltaY = e.clientY - startY;
                const newCodeHeight = startCodeHeight + deltaY;

                // Get right pane total height
                const rightPaneHeight = rightPane.offsetHeight;
                const dividerHeight = 8; // vertical divider height

                // Calculate constraints (20% min, 80% max for each section)
                const minCodeHeight = rightPaneHeight * 0.2;
                const maxCodeHeight = rightPaneHeight * 0.8;

                // Constrain the new height
                const constrainedCodeHeight = Math.max(minCodeHeight, Math.min(maxCodeHeight, newCodeHeight));
                const testHeight = rightPaneHeight - constrainedCodeHeight - dividerHeight;

                // Apply the heights using flexBasis for better control
                codeEditorSection.style.height = constrainedCodeHeight + 'px';
                codeEditorSection.style.flexBasis = constrainedCodeHeight + 'px';
                codeEditorSection.style.flexGrow = '0';
                codeEditorSection.style.flexShrink = '0';

                testResultsSection.style.height = testHeight + 'px';
                testResultsSection.style.flexBasis = testHeight + 'px';
                testResultsSection.style.flexGrow = '0';
                testResultsSection.style.flexShrink = '0';

                // Force Monaco to relayout
                if (window.monacoEditor) {
                    requestAnimationFrame(() => {
                        window.monacoEditor.layout();
                    });
                }
            }
        });

        document.addEventListener('touchmove', function(e) {
            if (isDragging || isVerticalDragging) {
                const touch = e.touches[0];
                const event = {
                    clientX: touch.clientX,
                    clientY: touch.clientY,
                    preventDefault: () => e.preventDefault()
                };
                document.dispatchEvent(new MouseEvent('mousemove', event));
            }
        });

        document.addEventListener('mouseup', function() {
            if (isDragging) {
                isDragging = false;
                divider.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }

            if (isVerticalDragging) {
                isVerticalDragging = false;
                verticalDivider.classList.remove('dragging');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });

        document.addEventListener('touchend', function() {
            if (isDragging) {
                isDragging = false;
                divider.classList.remove('dragging');
            }
            if (isVerticalDragging) {
                isVerticalDragging = false;
                verticalDivider.classList.remove('dragging');
            }
        });

        // Handle window resize
        window.addEventListener('resize', function() {
            if (window.monacoEditor) {
                window.monacoEditor.layout();
            }
        });

        // Set up event listeners after DOM is loaded
        document.addEventListener('DOMContentLoaded', function() {
            // Problem modal button
            const modalBtn = document.getElementById('open-problem-modal');
            if (modalBtn) modalBtn.onclick = openProblemModal;

            // Run code button
            const runBtn = document.getElementById('run-code-btn');
            if (runBtn) runBtn.onclick = runCode;

            // Language select
            const langSelect = document.getElementById('language-select');
            if (langSelect) {
                langSelect.onchange = function(e) {
                    if (currentProblem && window.monacoEditor) {
                        const language = e.target.value;
                        const template = currentProblem.templates[language] || '';
                        monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);
                        window.monacoEditor.setValue(template);
                    }
                };
            }

            // Filter controls
            const diffFilter = document.getElementById('difficulty-filter');
            const compFilter = document.getElementById('company-filter');
            const sortFilter = document.getElementById('sort-filter');

            if (diffFilter) diffFilter.onchange = applyFilters;
            if (compFilter) compFilter.onchange = applyFilters;
            if (sortFilter) sortFilter.onchange = applyFilters;

            // Modal close on outside click
            const modal = document.getElementById('problem-modal');
            if (modal) {
                modal.onclick = function(e) {
                    if (e.target === this) closeProblemModal();
                };
            }
        });
    </script>
</body>
</html>
"""


def get_big_time_display():
    """Get current time and date for display"""
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")  # 11:50 AM format
    date_str = now.strftime("%A, %B %d")
    return {"big_time": time_str, "day_date": date_str}


# ADD THE MISSING HOMEPAGE ROUTE
@app.route('/')
def home():
    """Homepage - serves the CodeBench editor"""
    return render_template_string(CODEBENCH_EDIT_HTML)


@app.route('/set-theme', methods=['POST'])
def set_theme():
    try:
        data = request.get_json()
        theme = data.get('theme', 'dark')
        session['theme'] = theme
        return jsonify({'success': True, 'theme': theme})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/execute_command', methods=['POST'])
def execute_command():
    try:
        data = request.get_json()
        command = data.get('command', '')

        if not command:
            return jsonify({'error': 'No command provided'})

        # Execute command using subprocess
        import subprocess
        import shlex

        # Split command into arguments safely
        args = shlex.split(command)

        # Execute command
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)

        return jsonify({'output': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode})

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'})
    except FileNotFoundError:
        return jsonify({'error': f'Command not found: {command.split()[0]}'})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/codebench-editor')
def codebench_editor():
    """codebench-style editor with problem selection"""
    return render_template_string(CODEBENCH_EDIT_HTML)


@app.route('/codebench/run', methods=['POST'])
def codebench_run():
    """Execute codebench solution code"""
    try:
        data = request.get_json()
        code = data.get('code', '')
        language = data.get('language', 'python')

        if not code.strip():
            return jsonify({'error': 'No code provided'})

        # Create a temporary file with the code
        import tempfile
        import subprocess
        import os

        if language == 'python':
            # Write Python code to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name

            try:
                # Execute Python code
                result = subprocess.run(['python3', temp_file],
                                        capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    return jsonify({'output': result.stdout})
                else:
                    return jsonify({'error': result.stderr})
            finally:
                os.unlink(temp_file)

        elif language == 'java':
            # Extract class name from code
            import re
            class_match = re.search(r'public\s+class\s+(\w+)', code)
            if not class_match:
                return jsonify({'error': 'No public class found in Java code'})

            class_name = class_match.group(1)

            # Write Java code to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
                f.write(code)
                temp_file = f.name

            # Rename file to match class name
            java_file = os.path.join(os.path.dirname(temp_file), f'{class_name}.java')
            os.rename(temp_file, java_file)

            try:
                # Compile Java code
                compile_result = subprocess.run(['javac', java_file],
                                                capture_output=True, text=True, timeout=10)

                if compile_result.returncode != 0:
                    return jsonify({'error': f'Compilation error: {compile_result.stderr}'})

                # Execute Java code
                class_dir = os.path.dirname(java_file)
                result = subprocess.run(['java', '-cp', class_dir, class_name],
                                        capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    return jsonify({'output': result.stdout})
                else:
                    return jsonify({'error': result.stderr})
            finally:
                # Clean up
                if os.path.exists(java_file):
                    os.unlink(java_file)
                class_file = java_file.replace('.java', '.class')
                if os.path.exists(class_file):
                    os.unlink(class_file)

        else:
            return jsonify({'error': f'Unsupported language: {language}'})

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Code execution timed out'})
    except Exception as e:
        return jsonify({'error': f'Execution error: {str(e)}'})


@app.route('/codebench/problems', methods=['GET'])
def codebench_problems():
    """Get list of codebench problems from YAML file"""
    try:
        import yaml
        import os

        # Try to find the YAML file in the current directory
        yaml_path = os.path.join(os.path.dirname(__file__), 'codebench_problems.yml')
        if not os.path.exists(yaml_path):
            yaml_path = 'codebench_problems.yml'

        print(f"Looking for YAML file at: {yaml_path}")

        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        print(f"Loaded {len(data['problems'])} problems from YAML")
        return jsonify(data['problems'])

    except Exception as e:
        print(f"Error loading YAML: {e}")
        return jsonify({'error': f'Failed to load problems: {str(e)}'})


@app.route('/codebench/test', methods=['POST'])
def codebench_test():
    """Execute test cases for a specific problem"""
    try:
        data = request.get_json()
        code = data.get('code', '')
        language = data.get('language', 'python')
        problem_id = data.get('problem_id')

        if not code.strip():
            return jsonify({'error': 'No code provided'})

        # Load problems to get test cases
        import yaml
        import os

        yaml_path = os.path.join(os.path.dirname(__file__), 'codebench_problems.yml')
        if not os.path.exists(yaml_path):
            yaml_path = 'codebench_problems.yml'

        with open(yaml_path, 'r', encoding='utf-8') as f:
            problems_data = yaml.safe_load(f)

        # Find the specific problem
        problem = None
        for p in problems_data['problems']:
            if p['id'] == problem_id:
                problem = p
                break

        if not problem:
            return jsonify({'error': f'Problem {problem_id} not found'})

        test_cases = problem.get('test_cases', [])
        results = []
        passed = 0

        import tempfile
        import subprocess
        import os
        import json

        for i, test_case in enumerate(test_cases):
            test_input = test_case.get('input')
            expected_output = test_case.get('expected')

            try:
                if language == 'python':
                    # Handle the input structure properly
                    if problem_id == 1:  # Two Sum
                        nums = test_input.get('nums', [])
                        target = test_input.get('target', 0)
                        test_code = f"""
{code}

# Test execution
try:
    solution_obj = Solution()
    result = solution_obj.twoSum({nums}, {target})
    if result is None:
        print("[]")
    else:
        print(str(result).replace(' ', ''))
except Exception as e:
    import traceback
    print(f"ERROR: {{str(e)}}")
    traceback.print_exc()
"""
                    elif problem_id == 3:  # Longest Substring
                        s = test_input.get('s', '')
                        test_code = f"""
{code}

# Test execution
import json
import sys

try:
    solution_obj = Solution()
    result = solution_obj.lengthOfLongestSubstring({repr(s)})
    print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
                    elif problem_id == 4:  # Valid Parentheses
                        s = test_input.get('s', '')
                        test_code = f"""
{code}

# Test execution
import json
import sys

try:
    solution_obj = Solution()
    result = solution_obj.isValid({repr(s)})
    print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
                    elif problem_id == 5:  # Stock
                        prices = test_input.get('prices', [])
                        test_code = f"""
{code}

# Test execution
import json
import sys

try:
    solution_obj = Solution()
    result = solution_obj.maxProfit({prices})
    print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
                    else:
                        # Generic handler
                        test_code = f"""
{code}

# Test execution
import json
import sys

try:
    # Generic test handler
    result = {test_input}
    print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""

                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                        f.write(test_code)
                        temp_file = f.name

                    try:
                        print(f"Executing Python test for problem {problem_id}")
                        print(f"Test code:\n{test_code}")

                        result = subprocess.run(['python3', temp_file],
                                                capture_output=True, text=True, timeout=10)

                        print(f"Return code: {result.returncode}")
                        print(f"Stdout: {result.stdout}")
                        print(f"Stderr: {result.stderr}")

                        if result.returncode == 0:
                            try:
                                output_str = result.stdout.strip()

                                # Try to parse as JSON first
                                try:
                                    actual_output = json.loads(output_str)
                                except:
                                    # If not JSON, try to eval Python list/value
                                    try:
                                        actual_output = eval(output_str) if output_str != 'null' else None
                                    except:
                                        actual_output = output_str

                                is_correct = compare_outputs(actual_output, expected_output)
                                if is_correct:
                                    passed += 1

                                results.append({
                                    'input': test_input,
                                    'expected': expected_output,
                                    'actual': actual_output,
                                    'passed': is_correct,
                                    'error': None
                                })
                            except Exception as parse_error:
                                results.append({
                                    'input': test_input,
                                    'expected': expected_output,
                                    'actual': result.stdout.strip(),
                                    'passed': False,
                                    'error': f'Output parse error: {str(parse_error)}'
                                })
                        else:
                            results.append({
                                'input': test_input,
                                'expected': expected_output,
                                'actual': None,
                                'passed': False,
                                'error': result.stderr.strip()
                            })
                    finally:
                        os.unlink(temp_file)

                elif language == 'java':
                    # Java test execution - similar approach
                    import re

                    # More flexible class detection
                    has_solution_class = 'class Solution' in code
                    class_match = re.search(r'public\s+class\s+(\w+)', code)

                    if not has_solution_class and not class_match:
                        results.append({
                            'input': test_input,
                            'expected': expected_output,
                            'actual': None,
                            'passed': False,
                            'error': 'No class found in Java code'
                        })
                        continue

                    # Create Java test runner
                    if problem_id == 1:  # Two Sum
                        nums = test_input.get('nums', [])
                        target = test_input.get('target', 0)
                        nums_array = '{' + ','.join(map(str, nums)) + '}'

                        test_code = f"""
{code}

import java.util.*;

public class TestRunner {{
    public static void main(String[] args) {{
        Solution solution = new Solution();
        try {{
            int[] nums = {nums_array};
            int target = {target};
            int[] result = solution.twoSum(nums, target);
            System.out.print("[");
            for (int i = 0; i < result.length; i++) {{
                System.out.print(result[i]);
                if (i < result.length - 1) System.out.print(",");
            }}
            System.out.println("]");
        }} catch (Exception e) {{
            System.err.println("ERROR: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }}
    }}
}}
"""
                    else:
                        # Generic Java test
                        test_code = f"""
{code}

public class TestRunner {{
    public static void main(String[] args) {{
        System.out.println("Java test execution not implemented for this problem");
    }}
}}
"""

                    with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
                        f.write(test_code)
                        temp_file = f.name

                    java_file = os.path.join(os.path.dirname(temp_file), 'TestRunner.java')
                    os.rename(temp_file, java_file)

                    try:
                        # Compile
                        compile_result = subprocess.run(['javac', java_file],
                                                        capture_output=True, text=True, timeout=10)

                        if compile_result.returncode != 0:
                            results.append({
                                'input': test_input,
                                'expected': expected_output,
                                'actual': None,
                                'passed': False,
                                'error': f'Compilation error: {compile_result.stderr}'
                            })
                            continue

                        # Execute
                        class_dir = os.path.dirname(java_file)
                        result = subprocess.run(['java', '-cp', class_dir, 'TestRunner'],
                                                capture_output=True, text=True, timeout=5)

                        if result.returncode == 0:
                            try:
                                # Parse Java output
                                output_str = result.stdout.strip()
                                if output_str.startswith('[') and output_str.endswith(']'):
                                    # Parse array output like [0,1]
                                    actual_output = json.loads(output_str)
                                else:
                                    actual_output = output_str

                                is_correct = compare_outputs(actual_output, expected_output)
                                if is_correct:
                                    passed += 1
                                results.append({
                                    'input': test_input,
                                    'expected': expected_output,
                                    'actual': actual_output,
                                    'passed': is_correct,
                                    'error': None
                                })
                            except (json.JSONDecodeError, ValueError):
                                results.append({
                                    'input': test_input,
                                    'expected': expected_output,
                                    'actual': result.stdout.strip(),
                                    'passed': False,
                                    'error': 'Invalid output format'
                                })
                        else:
                            results.append({
                                'input': test_input,
                                'expected': expected_output,
                                'actual': None,
                                'passed': False,
                                'error': result.stderr.strip()
                            })
                    finally:
                        # Clean up
                        if os.path.exists(java_file):
                            os.unlink(java_file)
                        class_file = java_file.replace('.java', '.class')
                        if os.path.exists(class_file):
                            os.unlink(class_file)

            except Exception as e:
                results.append({
                    'input': test_input,
                    'expected': expected_output,
                    'actual': None,
                    'passed': False,
                    'error': str(e)
                })

        return jsonify({
            'passed': passed,
            'total': len(test_cases),
            'test_cases': results
        })

    except Exception as e:
        return jsonify({'error': f'Test execution error: {str(e)}'})


def compare_outputs(actual, expected):
    """Compare actual output with expected output"""
    if isinstance(expected, list) and isinstance(actual, list):
        # For array problems like Two Sum, order might matter or not
        # For Two Sum specifically, any valid pair is correct
        return sorted(actual) == sorted(expected)
    else:
        return actual == expected


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9001"))  # Changed to 9001
    debug = os.environ.get("FLASK_ENV", "development") == "development"

    # Only open browser in local development
    if debug and port != int(os.environ.get("PORT", "9001")):
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            pass

    print(f"Starting CodeBench on port {port}")
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=True)
