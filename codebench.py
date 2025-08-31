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
app.secret_key = 'codebench_public_key'

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

                // Sync content back to main editor
                if (editorFullscreen && window.monacoEditor) {
                    const value = editorFullscreen.getValue();
                    const language = editorFullscreen.getModel().getLanguageId();

                    // Update main editor
                    window.monacoEditor.setValue(value);
                    monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);

                    // Destroy fullscreen editor
                    editorFullscreen.dispose();
                    editorFullscreen = null;

                    // Clear container
                    container.innerHTML = '';

                    // Force layout refresh
                    setTimeout(() => {
                        window.monacoEditor.layout();
                        window.dispatchEvent(new Event('resize'));
                    }, 100);
                }
            } else {
                overlay.classList.add('active');
                container.innerHTML = '<div id="editor-fs" style="width: 100%; height: 100%;"></div>';

                // Create fullscreen editor
                if (window.monaco && window.monacoEditor) {
                    const value = window.monacoEditor.getValue();
                    const language = window.monacoEditor.getModel().getLanguageId();

                    const currentTheme = document.body.classList.contains('theme-light') ? 'vs' : 'codebench-dark-theme';
                    editorFullscreen = monaco.editor.create(document.getElementById('editor-fs'), {
                        value: value,
                        language: language,
                        theme: currentTheme,
                        scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                        minimap: { enabled: false },
                        automaticLayout: true,
                        fontLigatures: true,
                        roundedSelection: false,
                        renderLineHighlight: 'line',
                        fontLigatures: true,
                        fontWeight: '400',
                        fontFamily: "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
                        tabSize: 4,
                        insertSpaces: true,
                        padding: { top: 0, bottom: 0 },
                        occurrencesHighlight: false, // Disable word highlighting on click
                        selectionHighlight: false, // Disable selection highlighting
                        wordHighlightDelay: 0 // Disable word highlight delay
                    });

                    // Sync changes back continuously
                    let isSyncing = false;
                    editorFullscreen.onDidChangeModelContent(() => {
                        if (!isSyncing && window.monacoEditor) {
                            isSyncing = true;
                            window.monacoEditor.setValue(editorFullscreen.getValue());
                            isSyncing = false;
                        }
                    });

                    // Sync language select
                    document.getElementById('language-select-fs').value = language;
                    document.getElementById('language-select-fs').onchange = function(e) {
                        const newLang = e.target.value;
                        if (editorFullscreen) {
                            monaco.editor.setModelLanguage(editorFullscreen.getModel(), newLang);
                        }
                        if (window.monacoEditor) {
                            monaco.editor.setModelLanguage(window.monacoEditor.getModel(), newLang);
                        }
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
        // Apply saved theme ASAP to avoid flash. Prefer 'codebench-theme', migrate from legacy keys
        (function() {
            let saved = localStorage.getItem('codebench-theme');
            if (!saved) {
                // migrate from 'workbench-theme'
                const wb = localStorage.getItem('workbench-theme');
                if (wb) saved = wb;
            }
            if (!saved) {
                // migrate from very old 'wb_theme'
                const legacy = localStorage.getItem('wb_theme');
                if (legacy) saved = legacy === 'light' ? 'light' : 'dark';
            }
            if (saved === 'white') saved = 'light';
            if (!saved) saved = 'dark';
            // persist normalized key
            localStorage.setItem('codebench-theme', saved);

            if (saved === 'light') {
                // Light theme classes
                document.documentElement.classList.remove('dark-theme');
                if (document.body) {
                    document.body.classList.remove('dark-theme');
                    document.body.classList.add('theme-light');
                }
                const s = document.createElement('style'); s.textContent = 'html, body { background:#f8fafc!important; }'; document.head.appendChild(s);
            } else {
                // Dark theme classes
                document.documentElement.classList.add('dark-theme');
                if (document.body) {
                    document.body.classList.remove('theme-light');
                    document.body.classList.add('dark-theme');
                }
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
        body, html { margin: 0; padding: 0; background-color: #0f172a !important; color: #e2e8f0; height: 100%; overflow: hidden; }
        /* Hide page-level scrollbar across browsers */
        html, body { scrollbar-width: none; -ms-overflow-style: none; }
        html::-webkit-scrollbar, body::-webkit-scrollbar { width: 0; height: 0; }
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
        .btn-expand { width: 40px; height: 40px; padding: 0; background-color: transparent; color: #94a3b8; border: 1px solid #475569; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; }
        .btn-expand:hover { background-color: #334155; color: #e2e8f0; border-color: #64748b; }
        .fullscreen-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background-color: #0f172a; z-index: 9999; display: none; }
        .fullscreen-overlay.active { display: flex; flex-direction: column; }
        .fullscreen-header { height: 60px; padding: 12px 20px; border-bottom: 1px solid #334155; background-color: #1e293b; display: flex; align-items: center; justify-content: space-between; }
        .fullscreen-content { flex: 1; padding: 20px; overflow-y: auto; background-color: #1e293b; }
        #test-results-fullscreen-content { background-color: #0f172a; }
        /* Hide native scrollbars but keep scrolling (we already provide custom/inner scrollers) */
        #problem-statement, .fullscreen-content, #test-results, #test-results-fullscreen-content {
            scrollbar-width: none; /* Firefox */
            -ms-overflow-style: none; /* IE/Edge */
        }
        #problem-statement::-webkit-scrollbar,
        .fullscreen-content::-webkit-scrollbar,
        #test-results::-webkit-scrollbar,
        #test-results-fullscreen-content::-webkit-scrollbar {
            width: 0; height: 0; /* WebKit */
        }
        .theme-select { border: 1px solid #475569; padding: 8px 12px; height: 36px; background-color: #334155; color: #e2e8f0; font-size: 14px; border-radius: 0; -webkit-appearance: menulist; -moz-appearance: menulist; appearance: auto; }
        .dark-theme .theme-select { background-color: #334155 !important; color: #e2e8f0 !important; border-color: #475569 !important; }
        body.theme-light .theme-select { background-color: #ffffff !important; color: #374151 !important; border-color: #d1d5db !important; }
        .monaco-editor, .monaco-editor *:not(.codicon) { font-family: 'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', ui-monospace, SFMono-Regular, Menlo, Monaco, monospace !important; font-variant-ligatures: contextual; }
        .monaco-editor .codicon, .codicon { font: normal normal normal 16px/1 codicon !important; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.75); display: none; z-index: 1000; backdrop-filter: blur(4px); }
        .modal.show { display: flex; align-items: center; justify-content: center; animation: fadeIn 0.2s ease; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .modal-content { background-color: #1e293b; border-radius: 0; padding: 0; max-width: 900px; max-height: 80vh; width: 90%; overflow: hidden; border: 1px solid #334155; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04); }
        .modal-header { padding: 20px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; background-color: #1e293b; }
        .modal-close { border: none !important; background: transparent !important; box-shadow: none !important; outline: none !important; color: #cbd5e1; }
        .modal-close:hover { background: transparent !important; opacity: 0.9; }
        .modal-close:focus { outline: none !important; box-shadow: none !important; }
        .modal-body { padding: 12px 8px; max-height: 60vh; overflow-y: auto; }
        .tag { font-size: 9.5px; padding: 1px 6px; border-radius: 0; margin-right: 6px; margin-bottom: 4px; display: inline-block; text-transform: uppercase; }
        .tag-easy { background-color: rgba(16, 185, 129, 0.2); color: #10b981; }
        .tag-medium { background-color: rgba(245, 158, 11, 0.2); color: #f59e0b; }
        .tag-hard { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; }
        .tag-company { background-color: rgba(59, 130, 246, 0.2); color: #3b82f6; }
        .tag-category { background-color: rgba(139, 92, 246, 0.2); color: #8b5cf6; }
        .problem-row { padding: 8px 8px; cursor: pointer; transition: all 0.15s ease; background-color: transparent; border-bottom: 1px solid #334155; }
        .problem-row:hover { background-color: rgba(99, 102, 241, 0.05); }
        body.theme-light .problem-row:hover { background-color: rgba(99, 102, 241, 0.08); }
        .problem-row:last-child { border-bottom: none; }
        .problem-row.selected { background-color: rgba(99, 102, 241, 0.1); }
        .filter-section { margin-bottom: 20px; padding: 16px 20px; background-color: #0f172a; border-radius: 0; border: 1px solid #334155; }
        .filter-label { color: #94a3b8; font-size: 12px; font-weight: 500; margin-bottom: 6px; display: block; text-transform: uppercase; letter-spacing: 0.5px; }
        .test-case { background-color: #0f172a; border: 1px solid #334155; border-radius: 0; padding: 16px; margin-bottom: 12px; width: 100%; }
        .test-passed { border-color: #10b981; background-color: rgba(16, 185, 129, 0.08); }
        .test-failed { border-color: #ef4444; background-color: rgba(239, 68, 68, 0.08); }
        .test-case-title { color: #e2e8f0; font-size: 14px; font-weight: 600; }
        .test-label { color: #94a3b8; font-size: 12px; margin-bottom: 4px; font-weight: 500; }
        .test-value { color: #e2e8f0; font-family: 'Cascadia Code', 'Fira Code', 'Monaco', 'Menlo', monospace; font-size: 13px; }
        .test-output { color: #fca5a5; font-family: 'Cascadia Code', 'Fira Code', 'Monaco', 'Menlo', monospace; font-size: 13px; }
        .test-results-header { padding: 16px 20px; background-color: #1e293b; border: 1px solid #334155; margin-bottom: 16px; }
        .test-stat { font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
        .test-error-box { margin-top: 12px; padding: 10px; background-color: rgba(30, 41, 59, 0.5); border: 1px solid #334155; border-radius: 0; }
        .test-error-title { color: #ef4444; font-size: 12px; font-weight: 600; margin-bottom: 4px; }
        .test-error-message { color: #fca5a5; font-family: monospace; font-size: 11px; white-space: pre-wrap; word-break: break-all; }
        .interface-guide-box { background-color: rgba(30, 41, 59, 0.5); border: 1px solid #334155; padding: 24px; margin-bottom: 24px; }
        .interface-guide-title { margin: 0 0 20px 0; color: #e2e8f0; font-size: 18px; font-weight: 600; }
        .guide-icon { color: #94a3b8; }
        .guide-icon-success { color: #10b981; }
        .guide-item-title { color: #e2e8f0; font-size: 14px; font-weight: 500; margin-bottom: 2px; }
        .guide-item-desc { color: #94a3b8; font-size: 13px; }
        .custom-select { position: relative; display: inline-block; }
        .custom-select select { border-radius: 0 !important; border: 1px solid #475569 !important; background-color: #334155 !important; color: #e2e8f0 !important; font-family: inherit !important; padding: 8px 32px 8px 12px !important; font-size: 14px; height: 36px; width: 100%; cursor: pointer; -webkit-appearance: none; -moz-appearance: none; appearance: none; background-image: none; }
        body.theme-light .custom-select select { background-color: #ffffff !important; color: #374151 !important; border-color: #d1d5db !important; }
        .custom-select::after { content: ''; position: absolute; top: 50%; right: 12px; transform: translateY(-50%); width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #e2e8f0; pointer-events: none; }
        body.theme-light .custom-select::after { border-top-color: #6b7280; }
        .custom-select select:hover { border-color: #64748b; }
        body.theme-light .custom-select select:hover { border-color: #9ca3af !important; }
        .custom-select select:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2); }
        .custom-select select option { background-color: #334155 !important; color: #e2e8f0 !important; padding: 8px 12px; }
        body.theme-light .custom-select select option { background-color: #ffffff !important; color: #374151 !important; }
        select::-ms-expand { display: none; }
        .markdown-content { padding-top: 0 !important; margin-top: 0 !important; }
        .markdown-content > :first-child { margin-top: 0 !important; padding-top: 0 !important; }
        .markdown-content h1, .markdown-content h2, .markdown-content h3, .markdown-content h4 { color: #f1f5f9; margin: 8px 0 8px 0; font-weight: 600; }
        .markdown-content h1 { font-size: 20px; }
        .markdown-content h2 { font-size: 18px; }
        .markdown-content h3 { font-size: 16px; margin: 8px 0 4px 0; }
        .markdown-content h4 { font-size: 15px; }
        .markdown-content h1:first-child, .markdown-content h2:first-child, .markdown-content h3:first-child { margin-top: 0; }
        .markdown-content p { margin: 12px 0; color: #cbd5e1; line-height: 1.6; }
        .markdown-content strong { color: #f1f5f9; font-weight: 600; }
        .markdown-content code { background-color: #334155; padding: 3px 6px; border-radius: 3px; font-family: 'Cascadia Code', 'Fira Code', 'Monaco', 'Menlo', 'Courier New', monospace; color: #e2e8f0; border: 1px solid #475569; font-size: 14px; }
        .markdown-content pre { background-color: #0f172a; padding: 12px; border-radius: 0; margin: 8px 0; border: 1px solid #334155; overflow-x: auto; display: block; }
        .markdown-content h3 + pre, .markdown-content h4 + pre, .markdown-content p + pre { margin-top: 8px !important; }
        .markdown-content pre + p, .markdown-content pre + h3, .markdown-content pre + h4 { margin-top: 16px !important; }
        .markdown-content pre code { background-color: transparent; border: none; padding: 0; margin: 0; color: #e2e8f0; font-size: 14px; line-height: 1.5; display: block; white-space: pre; font-family: 'Cascadia Code', 'Fira Code', 'Monaco', 'Menlo', 'Courier New', monospace; }
        .markdown-content ul, .markdown-content ol { margin: 12px 0; padding-left: 24px; }
        .markdown-content li { margin: 6px 0; color: #cbd5e1; line-height: 1.6; }
        .markdown-content blockquote { border-left: 4px solid #475569; margin: 16px 0; padding-left: 16px; color: #94a3b8; font-style: italic; }
        .divider { width: 2px; background-color: #475569; cursor: col-resize; position: relative; transition: background-color 0.2s; flex-shrink: 0; }
        .divider:hover { background-color: #64748b; }
        .divider.dragging { background-color: #6366f1; }
        .vertical-divider { height: 8px; background-color: #475569; cursor: row-resize; position: relative; transition: background-color 0.2s; touch-action: none; z-index: 3; flex-shrink: 0; }
        .vertical-divider::before { content: ''; position: absolute; left: 0; right: 0; top: -6px; bottom: -6px; cursor: row-resize; }
        .vertical-divider:hover { background-color: #64748b; }
        .vertical-divider.dragging { background-color: #6366f1; }
        body.theme-light { background-color: #f8f9fa !important; color: #111827 !important; }
        /* Ensure editor container background matches theme so Monaco colors are visible */
        body.theme-light #editor { background-color: #ffffff !important; }
        body.dark-theme #editor, .dark-theme #editor { background-color: #1e1e1e !important; }
        body.theme-light #top-header { background-color: #f3f4f6 !important; border-bottom-color: #d1d5db !important; }
        body.theme-light #left-pane { background-color: #f8f9fa !important; }
        body.theme-light #left-pane > div:first-child { background-color: #f3f4f6 !important; border-bottom-color: #d1d5db !important; }
        body.theme-light #problem-statement { background-color: #f8f9fa !important; }
        body.theme-light .divider { background-color: #d1d5db !important; }
        body.theme-light .vertical-divider { background-color: #d1d5db !important; }
        body.theme-light #right-pane { background-color: #f8f9fa !important; }
        body.theme-light #editor-controls { background-color: #f3f4f6 !important; border-bottom-color: #d1d5db !important; }
        body.theme-light #test-results-section { background-color: #f8f9fa !important; }
        body.theme-light #test-results-section > div:first-child { background-color: #f3f4f6 !important; border-bottom-color: #d1d5db !important; }
        body.theme-light #test-results { background-color: #f8f9fa !important; }
        body.theme-light .problem-row { background-color: transparent !important; border-bottom-color: #d1d5db !important; color: #374151 !important; }
        body.theme-light .problem-row:hover { background-color: rgba(99, 102, 241, 0.05) !important; }
        body.theme-light .problem-row span { color: #374151 !important; }
        body.theme-light .filter-section { background-color: #ffffff !important; border-color: #d1d5db !important; }
        body.theme-light .filter-label { color: #6b7280 !important; }
        body.theme-light .markdown-content { color: #374151 !important; }
        body.theme-light .markdown-content h1, body.theme-light .markdown-content h2, body.theme-light .markdown-content h3, body.theme-light .markdown-content h4 { color: #111827 !important; }
        body.theme-light .markdown-content p { color: #4b5563 !important; }
        body.theme-light .markdown-content li { color: #4b5563 !important; }
        body.theme-light .markdown-content strong { color: #1f2937 !important; }
        body.theme-light .markdown-content code { background-color: #f3f4f6; color: #1f2937; border-color: #e5e7eb; }
        body.theme-light .markdown-content pre { background-color: #f9fafb; border-color: #e5e7eb; }
        body.theme-light .markdown-content pre code { color: #111827; background-color: transparent; }
        body.theme-light .test-case { background-color: #ffffff !important; border-color: #d1d5db !important; }
        body.theme-light .test-case-title { color: #1f2937 !important; }
        body.theme-light .test-label { color: #6b7280 !important; }
        body.theme-light .test-value { color: #374151 !important; }
        body.theme-light .test-output { color: #dc2626 !important; }
        body.theme-light .test-passed { background-color: rgba(16, 185, 129, 0.06) !important; border-color: #10b981 !important; }
        body.theme-light .test-failed { background-color: rgba(239, 68, 68, 0.06) !important; border-color: #ef4444 !important; }
        body.theme-light .test-results-header { background-color: #f3f4f6 !important; border-color: #d1d5db !important; }
        body.theme-light .test-error-box { background-color: rgba(254, 242, 242, 0.8) !important; border-color: #fca5a5 !important; }
        body.theme-light .test-error-title { color: #dc2626 !important; }
        body.theme-light .test-error-message { color: #991b1b !important; }
        body.theme-light .modal { background-color: rgba(0,0,0,0.3) !important; }
        body.theme-light .modal-content { background-color: #f8f9fa !important; border-color: #d1d5db !important; }
        body.theme-light .modal-header { background-color: #f3f4f6 !important; border-color: #d1d5db !important; color: #111827 !important; }
        body.theme-light .modal-header h2 { color: #111827 !important; }
        body.theme-light .modal-header button { color: #6b7280 !important; }
        body.theme-light .modal-body { background-color: #f8f9fa !important; }
        body.theme-light .modal-body label { color: #6b7280 !important; }
        body.theme-light .btn-ghost { color: #6b7280 !important; border-color: #d1d5db !important; background-color: transparent !important; }
        body.theme-light .btn-ghost:hover { background-color: #e5e7eb !important; border-color: #9ca3af !important; }
        body.theme-light .btn-expand { color: #6b7280 !important; border-color: #d1d5db !important; background-color: transparent !important; }
        body.theme-light .btn-expand:hover { background-color: #e5e7eb !important; color: #374151 !important; border-color: #9ca3af !important; }
        body.theme-light .tag { background-color: #e5e7eb !important; color: #4b5563 !important; }
        body.theme-light .tag-easy { background-color: rgba(16,185,129,0.15) !important; color: #059669 !important; }
        body.theme-light .tag-medium { background-color: rgba(245,158,11,0.15) !important; color: #d97706 !important; }
        body.theme-light .tag-hard { background-color: rgba(239,68,68,0.15) !important; color: #dc2626 !important; }
        body.theme-light .fullscreen-overlay { background-color: #f8f9fa !important; }
        body.theme-light .fullscreen-header { background-color: #f3f4f6 !important; border-color: #d1d5db !important; }
        body.theme-light .fullscreen-content { background-color: #f8f9fa !important; }
        body.theme-light #problem-fullscreen-content { background-color: #f8f9fa !important; }
        body.theme-light #test-results-fullscreen-content { background-color: #f8f9fa !important; }
        body.theme-light h1, body.theme-light h2, body.theme-light h3, body.theme-light h4 { color: #111827 !important; }
        body.theme-light #problem-statement h1 { color: #111827 !important; }
        body.theme-light #problem-statement h3 { color: #1f2937 !important; }
        body.theme-light #problem-statement p { color: #6b7280 !important; }
        body.theme-light #problem-fullscreen-content h1 { color: #111827 !important; }
        body.theme-light #problem-fullscreen-content h3 { color: #1f2937 !important; }
        body.theme-light #problem-fullscreen-content p { color: #6b7280 !important; }
        body.theme-light #problem-fullscreen-content svg { stroke: #6b7280 !important; }
        body.theme-light .interface-guide-box { background-color: rgba(243, 244, 246, 0.8) !important; border-color: #d1d5db !important; }
        body.theme-light .interface-guide-title { color: #1f2937 !important; }
        body.theme-light .guide-icon { color: #6b7280 !important; }
        body.theme-light .guide-icon-success { color: #059669 !important; }
        body.theme-light .guide-item-title { color: #1f2937 !important; }
        body.theme-light .guide-item-desc { color: #6b7280 !important; }
        
        /* Theme-aware loading animation colors */
        :root {
            --bg-circle-color: #e5e7eb;
            --active-circle-color: #6366f1;
        }
        
        body.theme-light {
            --bg-circle-color: #d1d5db;
            --active-circle-color: #4f46e5;
        }
        
        body.dark-theme {
            --bg-circle-color: #475569;
            --active-circle-color: #6366f1;
        }
    </style>
</head>
<body>
    <!-- Header -->
    <div id="top-header" style="padding: 15px 20px; border-bottom: 1px solid #334155; background-color: #1e293b; display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 12px;">
            <a href="{{ url_for('home') }}" style="color: #e2e8f0; text-decoration: none; display: flex; align-items: center;">
                <div style="display: flex; align-items: baseline; line-height: 1;">
                    <span id="header-code" style="font-size: 30px; font-weight: 450; color: #e2e8f0; font-family: 'Inter', -apple-system, system-ui, sans-serif;">Code</span>
                    <span id="header-bench" style="font-size: 30px; font-weight: 600; color: #e2e8f0; font-family: 'Inter', -apple-system, system-ui, sans-serif;">Bench.</span>
                </div>
            </a>
        </div>
        <div style="display: flex; gap: 10px;">
            <button id="theme-toggle" class="btn btn-ghost" title="Toggle Theme" style="height: 40px; width: 40px; padding: 0; display: inline-flex; align-items: center; justify-content: center;">
                <svg id="theme-icon-dark" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display: block;">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                </svg>
                <svg id="theme-icon-light" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display: none;">
                    <circle cx="12" cy="12" r="5"></circle>
                    <line x1="12" y1="1" x2="12" y2="3"></line>
                    <line x1="12" y1="21" x2="12" y2="23"></line>
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                    <line x1="1" y1="12" x2="3" y2="12"></line>
                    <line x1="21" y1="12" x2="23" y2="12"></line>
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                </svg>
            </button>
        </div>
    </div>

    <!-- Main Layout -->
    <div id="main-container" style="height: calc(100vh - 72px); display: flex; position: relative; overflow: hidden;">
        <!-- Left Pane: Problem Statement -->
        <div id="left-pane" class="left-panel" style="width: 45%; min-width: 300px; background-color: #1e293b; display: flex; flex-direction: column;">
            <div style="height: 60px; padding: 12px 20px; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; gap: 10px;">
                <h3 style="margin: 0; color: #e2e8f0; font-size: 16px; font-weight: 600;">Problem Statement</h3>
                <div style="display: flex; gap: 8px;">
                    <button id="open-problem-modal" class="btn btn-ghost" title="Select Problem" aria-label="Select Problem" onclick="openProblemModal()" style="height: 40px; width: 40px; padding: 0; display: inline-flex; align-items: center; justify-content: center;">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                        </svg>
                    </button>
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
            <div id="problem-statement" style="flex: 1; padding: 16px 20px 16px 20px; overflow-y: auto;">
                <div style="max-width: 600px; margin: 0 auto; min-height: 100%; display: flex; flex-direction: column; justify-content: center;">
                    <div style="text-align: center; margin-bottom: 48px;">
                        <h1 style="margin: 0 0 12px 0; color: #e2e8f0; font-size: 32px; font-weight: 600; letter-spacing: -0.025em;">Welcome to <span id="welcome-code" style="font-weight: 450;">Code</span><span id="welcome-bench" style="font-weight: 600;">Bench.</span></h1>
                        <p style="margin: 0; color: #94a3b8; font-size: 16px; line-height: 1.5;">Master algorithmic thinking with interactive coding challenges</p>
                    </div>

                    <div class="interface-guide-box">
                        <h3 class="interface-guide-title">Interface Guide</h3>
                        <div style="display: grid; gap: 16px;">
                            <div style="display: flex; align-items: flex-start; gap: 14px;">
                                <svg class="guide-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                    <polyline points="14 2 14 8 20 8"></polyline>
                                </svg>
                                <div>
                                    <div class="guide-item-title">Select Problem</div>
                                    <div class="guide-item-desc">Browse and choose from coding challenges</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 14px;">
                                <svg class="guide-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;">
                                    <polygon points="6 4 20 12 6 20 6 4"></polygon>
                                </svg>
                                <div>
                                    <div class="guide-item-title">Run Code</div>
                                    <div class="guide-item-desc">Execute your solution against test cases</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 14px;">
                                <svg class="guide-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;">
                                    <polyline points="15 3 21 3 21 9"></polyline>
                                    <polyline points="9 21 3 21 3 15"></polyline>
                                </svg>
                                <div>
                                    <div class="guide-item-title">Fullscreen</div>
                                    <div class="guide-item-desc">Expand sections for focused coding</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: flex-start; gap: 14px;">
                                <svg class="guide-icon guide-icon-success" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;">
                                    <polyline points="20 6 9 17 4 12"></polyline>
                                </svg>
                                <div>
                                    <div class="guide-item-title">Completed</div>
                                    <div class="guide-item-desc">Problem successfully solved</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div style="text-align: center; margin-top: 36px;">
                        <button onclick="openProblemModal()" class="btn btn-ghost" style="font-size: 15px; padding: 12px 24px; height: auto; border-radius: 0; font-weight: 500;">
                            Get Started
                        </button>
                    </div>
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
                        <button id="run-code-btn" class="btn btn-ghost" style="height: 40px; width: 40px; padding: 0; font-size: 14px; display: inline-flex; align-items: center; justify-content: center;" disabled>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polygon points="6 4 20 12 6 20 6 4"></polygon>
                            </svg>
                        </button>
                    </div>
                    <div style="display: flex; gap: 15px; align-items: center;">
                        <select id="language-select" class="theme-select" onchange="changeLanguage(this.value)" style="height: 40px;">
                            <option value="java">Java</option>
                            <option value="python">Python</option>
                        </select>
                        <button class="btn-expand" title="Expand Code Editor" onclick="toggleEditorFullscreen()" style="height: 40px; width: 40px;">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="15 3 21 3 21 9"></polyline>
                                <polyline points="9 21 3 21 3 15"></polyline>
                                <line x1="21" y1="3" x2="14" y2="10"></line>
                                <line x1="3" y1="21" x2="10" y2="14"></line>
                            </svg>
                        </button>
                    </div>
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
                    <button class="btn-expand" title="Expand Test Results" onclick="toggleTestResultsFullscreen()" style="height: 40px; width: 40px;">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <polyline points="9 21 3 21 3 15"></polyline>
                            <line x1="21" y1="3" x2="14" y2="10"></line>
                            <line x1="3" y1="21" x2="10" y2="14"></line>
                        </svg>
                    </button>
                </div>
                <div id="test-results" style="flex: 1; padding: 20px; overflow-y: auto; display: flex; align-items: center; justify-content: center;">
                    <div style="text-align: center; color: #94a3b8;">
                        <p style="font-size: 16px; margin: 0;">Run your code to see test results</p>
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
        <div id="problem-fullscreen-content" class="fullscreen-content">
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
        <div id="test-results-fullscreen-content" class="fullscreen-content">
        </div>
    </div>

    <!-- Problem Selection Modal -->
    <div id="problem-modal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 style="margin: 0; color: #e2e8f0; font-size: 16px; font-weight: 600;">Select a Problem</h2>
                <button onclick="closeProblemModal()" class="modal-close" style="padding: 6px;">✕</button>
            </div>
            <div class="modal-body">
                <!-- Filters -->
                <div class="filter-section">
                    <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                        <div style="flex: 0 0 auto;">
                            <label class="filter-label">Company</label>
                            <div class="custom-select">
                                <select id="company-filter" style="width: auto;">
                                    <option value="">All Companies</option>
                                    <option value="Google">Google</option>
                                    <option value="Amazon">Amazon</option>
                                    <option value="Microsoft">Microsoft</option>
                                    <option value="Apple">Apple</option>
                                    <option value="Facebook">Facebook</option>
                                </select>
                            </div>
                        </div>
                        <div style="flex: 0 0 auto;">
                            <label class="filter-label">Category</label>
                            <div class="custom-select">
                                <select id="category-filter" style="width: auto;">
                                    <option value="">All Categories</option>
                                </select>
                            </div>
                        </div>
                        <div style="flex: 0 0 auto;">
                            <label class="filter-label">Difficulty</label>
                            <div class="custom-select">
                                <select id="difficulty-filter" style="width: auto;">
                                    <option value="">All Difficulties</option>
                                    <option value="Easy">Easy</option>
                                    <option value="Medium">Medium</option>
                                    <option value="Hard">Hard</option>
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

        // Completion tracking functions
        function getCompletedProblems() {
            const completed = localStorage.getItem('codebench-completed');
            return completed ? JSON.parse(completed) : {};
        }

        function markProblemCompleted(problemId) {
            const completed = getCompletedProblems();
            completed[problemId] = {
                completedAt: new Date().toISOString(),
                language: document.getElementById('language-select').value
            };
            localStorage.setItem('codebench-completed', JSON.stringify(completed));
        }

        function isProblemCompleted(problemId) {
            const completed = getCompletedProblems();
            return completed.hasOwnProperty(problemId);
        }

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
          const themeId = 'codebench-dark-theme';
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
          // Do not set theme globally here; return the theme id so caller can set conditionally
          return themeId;
        }

        // Load Monaco
        require.config({ paths: { 'vs': 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
        require(['vs/editor/editor.main'], function() {
          // Define custom themes (dark) without forcing it yet
          const darkId = applyDarkTheme();

          // Define light theme (VS Code Light+ inspired)
          monaco.editor.defineTheme('codebench-light', {
            base: 'vs',
            inherit: true,
            rules: [
              { token: 'comment', foreground: '6a737d', fontStyle: 'italic' },
              { token: 'keyword', foreground: '0000ff' },
              { token: 'storage', foreground: '0000ff' },
              { token: 'operator', foreground: '000000' },
              { token: 'string', foreground: 'a31515' },
              { token: 'number', foreground: '098658' },
              { token: 'regexp', foreground: '811f3f' },
              { token: 'delimiter', foreground: '24292e' },
              { token: 'variable', foreground: '24292e' },
              { token: 'variable.predefined', foreground: '0000ff' },
              { token: 'constant', foreground: '0070c1' },
              { token: 'type', foreground: '267f99' },
              { token: 'type.identifier', foreground: '267f99' },
              { token: 'class', foreground: '267f99' },
              { token: 'namespace', foreground: '267f99' },
              { token: 'interface', foreground: '267f99' },
              { token: 'enum', foreground: '267f99' },
              { token: 'function', foreground: '795e26' },
              { token: 'function.call', foreground: '795e26' },
              { token: 'method', foreground: '795e26' },
              { token: 'decorator', foreground: '795e26' },
              { token: 'invalid', foreground: 'ffffff', background: 'e51400' }
            ],
            colors: {
              'editor.background': '#ffffff',
              'editor.foreground': '#24292e',
              'editor.lineHighlightBackground': '#f6f8fa',
              'editorLineNumber.foreground': '#717171',
              'editorLineNumber.activeForeground': '#24292e',
              'editorIndentGuide.background': '#e1e4e8',
              'editorIndentGuide.activeBackground': '#c7c7c7',
              'editor.selectionBackground': '#cce5ff',
              'editor.inactiveSelectionBackground': '#e5e5e5',
              'editor.wordHighlightBackground': '#fff5b480',
              'editor.wordHighlightStrongBackground': '#ffea7f80',
              'editor.findMatchBackground': '#ffdf5d80',
              'editor.findMatchHighlightBackground': '#fff5b480',
              'editorCursor.foreground': '#000000',
              'editorWhitespace.foreground': '#d4d4d4'
            }
          });

          const initialLang = (document.getElementById('language-select') && document.getElementById('language-select').value) || 'java';
          const isLightTheme = document.body.classList.contains('theme-light');
          const themeIdToUse = isLightTheme ? 'vs' : darkId;
          try { monaco.editor.setTheme(themeIdToUse); } catch(e) {}
          window.monacoEditor = monaco.editor.create(document.getElementById('editor'), {
            value: '// Select a problem to start coding',
            language: initialLang,
            theme: themeIdToUse,
            scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
            minimap: { enabled: false },
            automaticLayout: true,
            fontLigatures: true,
            roundedSelection: false,
            renderLineHighlight: 'line',
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
            padding: { top: 0, bottom: 0 }, // Remove top padding
            occurrencesHighlight: false, // Disable word highlighting on click
            selectionHighlight: false, // Disable selection highlighting
            wordHighlightDelay: 0 // Disable word highlight delay
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
        document.addEventListener('DOMContentLoaded', function() {
            let savedTheme = localStorage.getItem('codebench-theme');
            if (!savedTheme) {
                const legacy = localStorage.getItem('wb_theme');
                if (legacy) {
                    savedTheme = legacy === 'light' ? 'light' : 'dark';
                    localStorage.setItem('codebench-theme', savedTheme);
                }
            }
            if (!savedTheme) savedTheme = 'dark';

            // Apply theme immediately
            setTimeout(() => {
                applyTheme(savedTheme);
            }, 50);
        });

        // Theme toggle button
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => {
                const currentTheme = document.body.classList.contains('theme-light') ? 'light' : 'dark';
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                applyTheme(newTheme);
            });
        }

        function applyTheme(theme) {
            const body = document.body;
            const root = document.documentElement;
            const darkIcon = document.getElementById('theme-icon-dark');
            const lightIcon = document.getElementById('theme-icon-light');
            const logoImage = document.getElementById('logo-image');
            const welcomeLogo = document.getElementById('welcome-logo');
            const headerCode = document.getElementById('header-code');
            const headerBench = document.getElementById('header-bench');
            const welcomeCode = document.getElementById('welcome-code');
            const welcomeBench = document.getElementById('welcome-bench');

            if (theme === 'light') {
                // toggle root/body classes
                root.classList.remove('dark-theme');
                body.classList.remove('dark-theme');
                body.classList.add('theme-light');

                // Update icons
                if (darkIcon) darkIcon.style.display = 'none';
                if (lightIcon) lightIcon.style.display = 'block';

                // Update logos for light theme
                if (logoImage) {
                    logoImage.src = '/asset/cb-black-logo.png';
                }
                if (welcomeLogo) {
                    welcomeLogo.src = '/asset/cb-black-logo.png';
                }

                // Update text colors for light theme
                if (headerCode) headerCode.style.color = '#374151';
                if (headerBench) headerBench.style.color = '#374151';
                if (welcomeCode) welcomeCode.style.color = '#374151';
                if (welcomeBench) welcomeBench.style.color = '#374151';

                try { 
                    if (window.monaco && window.monaco.editor) { 
                        // Use the exact VS Code Light+ theme
                        monaco.editor.setTheme('vs');
                        if (window.monacoEditor) {
                            monaco.editor.setModelLanguage(window.monacoEditor.getModel(), window.monacoEditor.getModel().getLanguageId());
                        }
                    } 
                } catch (e) {
                    console.warn('Failed to set light theme for Monaco:', e);
                }
            } else {
                // toggle root/body classes
                root.classList.add('dark-theme');
                body.classList.remove('theme-light');
                body.classList.add('dark-theme');

                // Update icons
                if (darkIcon) darkIcon.style.display = 'block';
                if (lightIcon) lightIcon.style.display = 'none';

                // Update logos for dark theme
                if (logoImage) {
                    logoImage.src = '/asset/cb-white-logo.png';
                }
                if (welcomeLogo) {
                    welcomeLogo.src = '/asset/cb-white-logo.png';
                }

                // Update text colors for dark theme
                if (headerCode) headerCode.style.color = '#e2e8f0';
                if (headerBench) headerBench.style.color = '#e2e8f0';
                if (welcomeCode) welcomeCode.style.color = '#e2e8f0';
                if (welcomeBench) welcomeCode.style.color = '#e2e8f0';

                try { 
                    if (window.monaco && window.monaco.editor && window.monacoEditor) { 
                        monaco.editor.setTheme('codebench-dark-theme'); 
                    } 
                } catch (e) {
                    console.warn('Failed to set dark theme for Monaco:', e);
                }
            }
            localStorage.setItem('codebench-theme', theme);
        }

        function loadProblems() {
            fetch('/codebench/problems')
            .then(response => response.json())
            .then(data => {
                allProblems = data;
                filteredProblems = [...allProblems];
                populateCategoryOptions();
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
                const row = document.createElement('div');
                row.className = 'problem-row';
                row.onclick = () => selectProblem(problem);

                const difficultyClass = problem.difficulty.toLowerCase();
                const isCompleted = isProblemCompleted(problem.id);

                row.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            ${isCompleted ? '<span style="color: #10b981; font-size: 16px; font-weight: 600;">✓</span>' : '<span style="width: 16px;"></span>'}
                            <span style="color: #e2e8f0; font-size: 15px; font-weight: 500;">${problem.title}</span>
                        </div>
                        <span class="tag tag-${difficultyClass}" style="margin-right:0;">${problem.difficulty.toUpperCase()}</span>
                    </div>
                `;

                container.appendChild(row);
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
        const label = ['Easy','Medium','Hard'].includes(tag) ? tag.toUpperCase() : tag;
        return `<span class="tag ${tagClass}">${label}</span>`;
    }).join('');

    // Normalize YAML indentation
    let normalizedMd = normalizeYamlMarkdown(problem.description);
    normalizedMd = stripHeadingFromMarkdown(normalizedMd, problem.title);
    
    // MARKDOWN PREPROCESSING
    // Fix Example patterns - ensure no gap between Example heading and code block
    normalizedMd = normalizedMd.replace(/\*\*(Example \d+:?)\*\*\s*\n+```/g, '**$1**\n```');
    
    // Fix Constraints pattern
    normalizedMd = normalizedMd.replace(/\*\*(Constraints:?)\*\*\s*\n+/g, '**$1**\n');
    
    // CRITICAL FIX: Process code blocks to ensure proper line breaks
    // Match all code blocks and fix their content
    normalizedMd = normalizedMd.replace(/```\n?([\s\S]*?)\n?```/g, function(match, content) {
        // Check if this looks like an Input/Output/Explanation block
        if (content.includes('Input:') && (content.includes('Output:') || content.includes('Explanation:'))) {
            // Fix the line breaks - add newlines before Output and Explanation
            let fixed = content;
            
            // Replace any occurrence of Output: that doesn't have a newline before it
            fixed = fixed.replace(/([^\n])(\s*)Output:/g, '$1\nOutput:');
            
            // Replace any occurrence of Explanation: that doesn't have a newline before it  
            fixed = fixed.replace(/([^\n])(\s*)Explanation:/g, '$1\nExplanation:');
            
            // Also handle cases where they're directly adjacent with no characters between
            fixed = fixed.replace(/\]Output:/g, ']\nOutput:');
            fixed = fixed.replace(/\]Explanation:/g, ']\nExplanation:');
            
            // Trim any extra whitespace
            fixed = fixed.trim();
            
            return '```\n' + fixed + '\n```';
        }
        return match;
    });
    
    // Remove excessive blank lines (keep max 2)
    normalizedMd = normalizedMd.replace(/\n{3,}/g, '\n\n');
    
    // Convert markdown to HTML
    let markedHtml = renderMarkdownSafe(normalizedMd);
    
    // HTML POST-PROCESSING
    // Remove empty paragraphs
    markedHtml = markedHtml.replace(/<p>\s*<\/p>/gi, '');
    markedHtml = markedHtml.replace(/<p>\s*<br\s*\/?>\s*<\/p>/gi, '');
    markedHtml = markedHtml.replace(/<p>&nbsp;<\/p>/gi, '');
    
    // Convert Example headings to h3
    markedHtml = markedHtml.replace(/<p>\s*<strong>(Example \d+:?)<\/strong>\s*<\/p>/gi, '<h3>$1</h3>');
    markedHtml = markedHtml.replace(/<p>\s*<strong>(Constraints:?)<\/strong>\s*<\/p>/gi, '<h3>$1</h3>');
    
    // Remove paragraphs wrapping pre blocks
    markedHtml = markedHtml.replace(/<p>\s*(<pre[^>]*>)/gi, '$1');
    markedHtml = markedHtml.replace(/(<\/pre>)\s*<\/p>/gi, '$1');
    
    // Remove gaps between headings and code blocks
    markedHtml = markedHtml.replace(/(<h[1-6][^>]*>.*?<\/h[1-6]>)\s*(<pre[^>]*>)/gi, '$1$2');
    
    statement.innerHTML = `
        <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <h2 style="margin: 0; color: #e2e8f0; font-size: 18px; font-weight: 600;">${problem.title}</h2>
                <span class="tag tag-${difficultyClass}" style="margin-right:0;">${problem.difficulty.toUpperCase()}</span>
            </div>
            <div style="margin-bottom: 8px;">${tagsHtml}</div>
        </div>
        <div class="markdown-content">
            ${markedHtml}
        </div>
    `;

    // Post-processing after DOM insertion
    // Post-processing after DOM insertion
    setTimeout(() => {
        const container = document.getElementById('problem-statement');
        const mdRoot = container.querySelector('.markdown-content');
        
        if (mdRoot) {
            // Process code blocks
            mdRoot.querySelectorAll('pre code').forEach((codeEl) => {
                // CRITICAL FIX: Handle <br> tags that the fallback renderer creates
                // Convert <br> tags to newlines before getting text content
                let htmlContent = codeEl.innerHTML;
                
                // Replace <br> tags with newlines
                htmlContent = htmlContent.replace(/<br\s*\/?>/gi, '\n');
                
                // Decode HTML entities properly
                let temp = document.createElement('textarea');
                temp.innerHTML = htmlContent;
                let text = temp.value;
                
                // Clean up: remove leading/trailing whitespace
                text = text.trim();
                
                // Ensure code blocks use monospace font
                codeEl.style.fontFamily = "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', monospace";
                
                // Set the cleaned text
                codeEl.textContent = text;
            });
            
            // Also ensure pre elements have proper styling
            mdRoot.querySelectorAll('pre').forEach((preEl) => {
                preEl.style.fontFamily = "'Cascadia Code', 'Fira Code', Consolas, 'Liberation Mono', 'Courier New', monospace";
                // Set consistent padding
                preEl.style.paddingTop = '12px';
                preEl.style.paddingBottom = '12px';
                preEl.style.paddingLeft = '12px';
                preEl.style.paddingRight = '12px';
            });
            
            // Remove any remaining empty paragraphs
            mdRoot.querySelectorAll('p').forEach((p) => {
                if (!p.textContent.trim() && !p.querySelector('*')) {
                    p.remove();
                }
            });
            
            // Style Example headings
            mdRoot.querySelectorAll('h3').forEach((h3) => {
                if (/Example \d+:?/.test(h3.textContent)) {
                    h3.style.marginBottom = '8px';
                    h3.style.marginTop = '16px';
                    const next = h3.nextElementSibling;
                    if (next && next.tagName === 'PRE') {
                        next.style.marginTop = '0';
                    }
                }
            });
            
            // Fix spacing
            mdRoot.querySelectorAll('pre + pre').forEach((pre) => {
                pre.style.marginTop = '8px';
            });
            
            mdRoot.querySelectorAll('h3 + pre, h4 + pre').forEach((pre) => {
                pre.style.marginTop = '0';
            });
        }
    }, 0);

    // Update editor
    const language = document.getElementById('language-select').value;
    const template = problem.templates[language] || '';

    if (window.monacoEditor) {
        monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);
        window.monacoEditor.setValue(template);
        window.monacoEditor.updateOptions({ readOnly: false });

        // Enable run button
        const runBtn = document.getElementById('run-code-btn');
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.onclick = runCode;
        }
    }
}

        function runCode() {
            if (!window.monacoEditor || !currentProblem) {
                console.warn('Editor not ready');
                return;
            }

            const code = window.monacoEditor.getValue();
            const language = document.getElementById('language-select').value;

            if (!code.trim()) {
                alert('Please write some code first!');
                return;
            }

            const runBtn = document.getElementById('run-code-btn');
            const resultsContainer = document.getElementById('test-results');

            // Change button to stop button
            runBtn.disabled = false;
            runBtn.onclick = stopCode;
            runBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="6" y="6" width="12" height="12"></rect>
                </svg>
            `;
            runBtn.title = "Stop Execution";
            
            resultsContainer.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: 200px;">
                    <div style="text-align: center;">
                        <div style="display: inline-block; position: relative;">
                            <svg width="48" height="48" viewBox="0 0 48 48" style="display: block;">
                                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--bg-circle-color, #e5e7eb)" stroke-width="3" opacity="0.3"/>
                                <circle cx="24" cy="24" r="20" fill="none" stroke="var(--active-circle-color, #6366f1)" stroke-width="3" stroke-linecap="round" stroke-dasharray="125.6" stroke-dashoffset="125.6">
                                    <animate attributeName="stroke-dashoffset" values="125.6;0;125.6" dur="2s" repeatCount="indefinite"/>
                                    <animateTransform attributeName="transform" type="rotate" values="0 24 24;360 24 24" dur="2s" repeatCount="indefinite"/>
                                </circle>
                            </svg>
                        </div>
                    </div>
                </div>
            `;

            // Store the fetch request for potential cancellation
            window.currentExecution = fetch('/codebench/test', {
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
                if (error.name !== 'AbortError') {
                    console.error('Error:', error);
                    resultsContainer.innerHTML = '<div style="color: #ef4444; text-align: center; padding: 20px;">❌ Failed to run tests</div>';
                }
            })
            .finally(() => {
                // Reset button to play button
                runBtn.disabled = false;
                runBtn.onclick = runCode;
                runBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>';
                runBtn.title = "Run Code";
                window.currentExecution = null;
            });
        }

        function stopCode() {
            if (window.currentExecution) {
                // Abort the current execution
                window.currentExecution.abort();
                window.currentExecution = null;
            }
            
            const runBtn = document.getElementById('run-code-btn');
            const resultsContainer = document.getElementById('test-results');
            
            // Reset button to play button
            runBtn.disabled = false;
            runBtn.onclick = runCode;
            runBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 4 20 12 6 20 6 4"></polygon></svg>';
            runBtn.title = "Run Code";
            
            // Show stopped message
            resultsContainer.innerHTML = '<div style="text-align: center; color: #6b7280; padding: 20px; font-size: 16px;">Execution stopped by user</div>';
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

            // Check if all test cases passed and mark problem as completed
            if (results.passed > 0 && results.passed === results.total) {
                markProblemCompleted(currentProblem.id);
            }

            const passed = results.passed || 0;
            const total = results.total || 0;
            const testCases = results.test_cases || [];
            const failed = total - passed;

            // Clear and set proper layout
            container.style.display = 'block';
            container.style.overflow = 'auto';

            let html = `
                <div class="test-results-header">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; gap: 20px; align-items: center;">
                            <span class="test-stat" style="color: ${passed > 0 ? '#10b981' : '#64748b'};">
                                <span style="font-size: 18px;">✓</span> ${passed} passed
                            </span>
                            <span class="test-stat" style="color: ${failed > 0 ? '#ef4444' : '#64748b'};">
                                <span style="font-size: 18px;">✗</span> ${failed} failed
                            </span>
                        </div>
                        <span style="color: #64748b; font-size: 14px;">Total: ${total}</span>
                    </div>
                </div>
            `;

            testCases.forEach((testCase, index) => {
                const status = testCase.passed ? 'test-passed' : 'test-failed';
                const statusIcon = testCase.passed ? '✓' : '✗';
                const statusColor = testCase.passed ? '#10b981' : '#ef4444';

                // Format input for display
                let inputDisplay = '';
                if (typeof testCase.input === 'object' && testCase.input !== null) {
                    // Format object inputs nicely
                    Object.entries(testCase.input).forEach(([key, value]) => {
                        if (inputDisplay) inputDisplay += ', ';
                        inputDisplay += `${key} = ${JSON.stringify(value)}`;
                    });
                } else {
                    inputDisplay = JSON.stringify(testCase.input);
                }

                html += `
                    <div class="test-case ${status}">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; cursor: pointer;" onclick="toggleTestCase(${index}, this)">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <svg id="chevron-${index}" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transition: transform 0.2s ease;">
                                    <polyline points="6 9 12 15 18 9"></polyline>
                                </svg>
                                <strong class="test-case-title">Test Case ${index + 1}</strong>
                            </div>
                            <span style="color: ${statusColor}; font-weight: 600; font-size: 13px;">${statusIcon} ${testCase.passed ? 'PASSED' : 'FAILED'}</span>
                        </div>
                        <div id="test-case-content-${index}" style="display: none; flex-direction: column; gap: 8px;">
                            <div>
                                <div class="test-label">Input:</div>
                                <div class="test-value" style="padding-left: 20px;">${inputDisplay}</div>
                            </div>
                            <div>
                                <div class="test-label">Expected:</div>
                                <div class="test-value" style="padding-left: 20px;">${JSON.stringify(testCase.expected)}</div>
                            </div>
                            ${!testCase.passed ? `
                            <div>
                                <div class="test-label">Output:</div>
                                <div class="test-output" style="padding-left: 20px;">${JSON.stringify(testCase.actual)}</div>
                            </div>
                            ` : ''}
                        </div>
                        ${testCase.error ? `
                        <div id="test-error-${index}" style="display: none;">
                            <div class="test-error-box">
                                <div class="test-error-title">Error:</div>
                                <div class="test-error-message">${testCase.error}</div>
                            </div>
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

        function toggleTestCase(index, el) {
            // Determine the correct container (fullscreen or inline) and scope DOM queries within it
            const container = (el && (el.closest('#test-results-fullscreen-content') || el.closest('#test-results'))) || document;

            // Use attribute selectors scoped to the container to avoid duplicate ID collisions
            const content = container.querySelector(`[id="test-case-content-${index}"]`);
            const error = container.querySelector(`[id="test-error-${index}"]`);
            const chevron = container.querySelector(`[id="chevron-${index}"]`);

            if (content) {
                const isVisible = content.style.display !== 'none';
                content.style.display = isVisible ? 'none' : 'flex';
                if (error) error.style.display = isVisible ? 'none' : 'block';

                if (chevron) {
                    chevron.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(90deg)';
                }
            }
        }

        // Event listeners
        (function(){
            const modalBtn = document.getElementById('open-problem-modal');
            if (modalBtn) modalBtn.onclick = openProblemModal;

            const runBtn = document.getElementById('run-code-btn');
            if (runBtn) runBtn.onclick = runCode;
        })();

        document.getElementById('language-select').onchange = function(e) {
            if (currentProblem && window.monacoEditor) {
                const language = e.target.value;
                const template = currentProblem.templates[language] || '';
                monaco.editor.setModelLanguage(window.monacoEditor.getModel(), language);
                window.monacoEditor.setValue(template);
            }
        };

        // Build category list from tags (exclude companies/difficulties)
        function populateCategoryOptions() {
            const catSelect = document.getElementById('category-filter');
            if (!catSelect) return;
            const companies = new Set(['Google','Amazon','Microsoft','Apple','Facebook','Meta']);
            const difficulties = new Set(['Easy','Medium','Hard']);
            const blacklist = new Set(['Top-50']);

            const cats = new Set();
            (allProblems || []).forEach(p => {
                (p.tags || []).forEach(t => {
                    if (!companies.has(t) && !difficulties.has(t) && !blacklist.has(t)) cats.add(t);
                });
            });

            const current = catSelect.value;
            // Reset options
            catSelect.innerHTML = '';
            const allOpt = document.createElement('option');
            allOpt.value = '';
            allOpt.textContent = 'All Categories';
            catSelect.appendChild(allOpt);
            Array.from(cats).sort((a,b)=>a.localeCompare(b)).forEach(t => {
                const opt = document.createElement('option');
                opt.value = t;
                opt.textContent = t;
                catSelect.appendChild(opt);
            });
            // Restore selection if still present
            if ([...catSelect.options].some(o => o.value === current)) catSelect.value = current;
        }

        // Filter functionality
        function applyFilters() {
            const difficulty = document.getElementById('difficulty-filter').value;
            const company = document.getElementById('company-filter').value;
            const category = document.getElementById('category-filter') ? document.getElementById('category-filter').value : '';

            filteredProblems = allProblems.filter(problem => {
                if (difficulty && problem.difficulty !== difficulty) return false;
                if (company && !(problem.tags || []).includes(company)) return false;
                if (category && !(problem.tags || []).includes(category)) return false;
                return true;
            });

            // Sort by problem ID by default
            filteredProblems.sort((a, b) => a.id - b.id);

            displayModalProblems();
        }

        document.getElementById('difficulty-filter').onchange = applyFilters;
        document.getElementById('company-filter').onchange = applyFilters;
        const catFilterInit = document.getElementById('category-filter');
        if (catFilterInit) catFilterInit.onchange = applyFilters;

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

            // Handle vertical dragging with strong clamping so header can't be dragged too far
            if (isVerticalDragging) {
                e.preventDefault();
                const deltaY = e.clientY - startY;
                const provisionalCodeHeight = startCodeHeight + deltaY;

                // Layout and constraints
                const rightPaneHeight = rightPane.offsetHeight;
                const dividerHeight = 8; // vertical divider height

                // Absolute minimums for comfortable UI
                const minCodeHeightPx = 280;   // keep editor usable
                const minTestHeightPx = 180;   // keep Test Results header + content visible

                // Available height for code editor considering minimum test area
                const availableForCode = Math.max(0, rightPaneHeight - dividerHeight - minTestHeightPx);

                // Dynamic minimum based on viewport + absolute floor
                const dynamicMinCode = Math.max(minCodeHeightPx, Math.floor(rightPaneHeight * 0.35));

                const minCodeHeight = Math.min(dynamicMinCode, availableForCode);
                const maxCodeHeight = availableForCode; // can't exceed available after reserving test area

                // Constrain
                const constrainedCodeHeight = Math.max(minCodeHeight, Math.min(maxCodeHeight, provisionalCodeHeight));
                const testHeight = Math.max(minTestHeightPx, rightPaneHeight - constrainedCodeHeight - dividerHeight);

                // Apply the heights using flex properties
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
                // Debounce resize events to prevent excessive layout calls
                clearTimeout(window.resizeTimeout);
                window.resizeTimeout = setTimeout(() => {
                    try {
                        window.monacoEditor.layout();
                    } catch (e) {
                        console.warn('Editor layout error:', e);
                    }
                }, 100);
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

            if (diffFilter) diffFilter.onchange = applyFilters;
            if (compFilter) compFilter.onchange = applyFilters;

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


def compare_outputs(actual, expected, comparison_strategy="exact"):
    """
    Compare actual output with expected output based on the comparison strategy.

    Strategies:
    - exact: Direct comparison
    - order_independent: For arrays/lists where order doesn't matter
    - custom: Problem-specific comparison (can be extended)
    """
    # Handle None/null cases
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False

    if comparison_strategy == "order_independent":
        # For arrays/lists where order doesn't matter
        if isinstance(actual, list) and isinstance(expected, list):
            # Handle nested lists (like Group Anagrams)
            if actual and expected and isinstance(actual[0], list) and isinstance(expected[0], list):
                # Sort each inner list and then sort the outer list
                actual_sorted = [sorted(inner) for inner in actual]
                expected_sorted = [sorted(inner) for inner in expected]
                return sorted(actual_sorted) == sorted(expected_sorted)
            else:
                # Handle simple lists
                return sorted(actual) == sorted(expected)

    # Default to exact comparison
    return actual == expected


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

        # Load problems to get test cases and metadata
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

        # Get problem metadata
        method_info = problem.get('method_info', {}).get(language, {})
        comparison_strategy = problem.get('comparison_strategy', 'exact')
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
                    result = run_python_test(
                        code, test_input, expected_output,
                        method_info, comparison_strategy
                    )
                elif language == 'java':
                    result = run_java_test(
                        code, test_input, expected_output,
                        method_info, comparison_strategy
                    )
                else:
                    result = {
                        'input': test_input,
                        'expected': expected_output,
                        'actual': None,
                        'passed': False,
                        'error': f'Unsupported language: {language}'
                    }

                if result['passed']:
                    passed += 1
                results.append(result)

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


def run_python_test(code, test_input, expected_output, method_info, comparison_strategy):
    """Run a Python test case using metadata from YAML"""
    import tempfile
    import subprocess
    import json

    # Extract method information
    method_name = method_info.get('method_name')
    parameters = method_info.get('parameters', [])
    return_type = method_info.get('return_type')
    return_is_linked_list = method_info.get('return_is_linked_list', False)
    returns_modified_input = method_info.get('returns_modified_input')
    helper_classes = method_info.get('helper_classes', '')

    if not method_name:
        return {
            'input': test_input,
            'expected': expected_output,
            'actual': None,
            'passed': False,
            'error': 'Method name not found in problem configuration'
        }

    # Build parameter setup code
    param_lines = []
    arg_names = []

    if isinstance(test_input, dict):
        for param in parameters:
            param_name = param['name']
            param_type = param.get('type', '')
            is_linked_list = param.get('is_linked_list', False)

            if param_name in test_input:
                value = test_input[param_name]

                if is_linked_list:
                    param_lines.append(f"{param_name}_arr = {repr(value)}")
                    param_lines.append(f"{param_name} = build_list({param_name}_arr)")
                else:
                    param_lines.append(f"{param_name} = {repr(value)}")

                arg_names.append(param_name)
    else:
        # Single parameter case
        if parameters:
            param_name = parameters[0]['name']
            param_lines.append(f"{param_name} = {repr(test_input)}")
            arg_names.append(param_name)

    param_setup_code = "\n".join(param_lines)
    args_str = ", ".join(arg_names)

    # Build test code
    test_code = f"""
{helper_classes}

{code}

# Test execution
import json
import sys

def build_list(arr):
    '''Convert array to linked list'''
    if not arr:
        return None
    head = ListNode(arr[0])
    current = head
    for val in arr[1:]:
        current.next = ListNode(val)
        current = current.next
    return head

def list_to_array(node):
    '''Convert linked list to array'''
    result = []
    while node:
        result.append(node.val)
        node = node.next
    return result

# Prepare inputs
{param_setup_code}

try:
    solution = Solution()
    result = solution.{method_name}({args_str})

    # Handle different return types
    if result is None:
        if "{returns_modified_input}" and "{returns_modified_input}" in locals():
            # Return the modified input parameter
            output = {returns_modified_input}
            if isinstance(output, list):
                print(json.dumps(output))
            else:
                print(json.dumps(output))
        else:
            print("null")
    elif {return_is_linked_list} and hasattr(result, 'val'):
        # Convert linked list to array
        print(json.dumps(list_to_array(result)))
    else:
        # Regular output
        print(json.dumps(result))
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        temp_file = f.name

    try:
        result = subprocess.run(
            ['python3', temp_file],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            try:
                output_str = result.stdout.strip()

                # Parse output
                try:
                    actual_output = json.loads(output_str)
                except Exception:
                    actual_output = output_str if output_str != 'null' else None

                # Compare outputs
                is_correct = compare_outputs(actual_output, expected_output, comparison_strategy)

                return {
                    'input': test_input,
                    'expected': expected_output,
                    'actual': actual_output,
                    'passed': is_correct,
                    'error': None
                }
            except Exception as e:
                return {
                    'input': test_input,
                    'expected': expected_output,
                    'actual': result.stdout.strip(),
                    'passed': False,
                    'error': f'Output parsing error: {str(e)}'
                }
        else:
            return {
                'input': test_input,
                'expected': expected_output,
                'actual': None,
                'passed': False,
                'error': result.stderr.strip()
            }
    finally:
        os.unlink(temp_file)


def run_java_test(code, test_input, expected_output, method_info, comparison_strategy):
    """Run a Java test case using metadata from YAML"""
    import tempfile
    import subprocess
    import json
    import re
    import os
    
    # Clean up any existing TestRunner files at the start of each test
    temp_dir = tempfile.gettempdir()
    for file in os.listdir(temp_dir):
        if file.startswith('TestRunner') and (file.endswith('.java') or file.endswith('.class')):
            try:
                os.unlink(os.path.join(temp_dir, file))
            except:
                pass

    # Extract method information
    method_name = method_info.get('method_name')
    parameters = method_info.get('parameters', [])
    return_type = method_info.get('return_type')
    return_is_linked_list = method_info.get('return_is_linked_list', False)
    returns_modified_input = method_info.get('returns_modified_input')
    helper_classes = method_info.get('helper_classes', '')

    if not method_name:
        return {
            'input': test_input,
            'expected': expected_output,
            'actual': None,
            'passed': False,
            'error': 'Method name not found in problem configuration'
        }

    # Check if Solution class exists
    if 'class Solution' not in code:
        return {
            'input': test_input,
            'expected': expected_output,
            'actual': None,
            'passed': False,
            'error': 'No Solution class found in Java code'
        }

    # Check if this problem uses ListNode
    uses_listnode = return_is_linked_list or any(
        param.get('is_linked_list', False) for param in parameters
    ) or 'ListNode' in helper_classes or 'ListNode' in code

    # Helper functions for Java literals
    def java_escape_string(s):
        return s.replace('\\', r'\\').replace('"', r'\"')

    def java_literal(value, param_type):
        if param_type == 'int[]' and isinstance(value, list):
            return 'new int[]{' + ','.join(str(x) for x in value) + '}'
        elif param_type == 'String[]' and isinstance(value, list):
            # Handle String[] type
            string_literals = [f'"{java_escape_string(str(x))}"' for x in value]
            return 'new String[]{' + ','.join(string_literals) + '}'
        elif param_type == 'String' and isinstance(value, str):
            return f'"{java_escape_string(value)}"'
        elif param_type == 'int' and isinstance(value, int):
            return str(value)
        elif param_type == 'boolean' and isinstance(value, bool):
            return 'true' if value else 'false'
        elif param_type == 'char[][]' and isinstance(value, list):
            rows = []
            for row in value:
                chars = ','.join(f"'{c}'" for c in row)
                rows.append('{' + chars + '}')
            return 'new char[][]{' + ','.join(rows) + '}'
        elif param_type == 'int[][]' and isinstance(value, list):
            # Handle int[][] type
            rows = []
            for row in value:
                row_literals = [str(x) for x in row]
                rows.append('{' + ','.join(row_literals) + '}')
            return 'new int[][]{' + ','.join(rows) + '}'
        elif param_type == 'String[][]' and isinstance(value, list):
            # Handle String[][] type
            rows = []
            for row in value:
                row_literals = [f'"{java_escape_string(str(x))}"' for x in row]
                rows.append('{' + ','.join(row_literals) + '}')
            return 'new String[][]{' + ','.join(rows) + '}'
        elif param_type == 'List<String>' and isinstance(value, list):
            # Handle List<String> type
            string_literals = [f'"{java_escape_string(str(x))}"' for x in value]
            return 'Arrays.asList(' + ','.join(string_literals) + ')'
        elif param_type == 'List<List<Integer>>' and isinstance(value, list):
            # Handle List<List<Integer>> type
            inner_lists = []
            for inner_list in value:
                inner_literals = [str(x) for x in inner_list]
                inner_lists.append('Arrays.asList(' + ','.join(inner_literals) + ')')
            return 'Arrays.asList(' + ','.join(inner_lists) + ')'
        elif param_type == 'List<List<String>>' and isinstance(value, list):
            # Handle List<List<String>> type
            inner_lists = []
            for inner_list in value:
                inner_literals = [f'"{java_escape_string(str(x))}"' for x in inner_list]
                inner_lists.append('Arrays.asList(' + ','.join(inner_literals) + ')')
            return 'Arrays.asList(' + ','.join(inner_lists) + ')'
        else:
            return f'"{java_escape_string(str(value))}"'

    # Build parameter setup
    var_lines = []
    arg_names = []

    if isinstance(test_input, dict):
        for param in parameters:
            param_name = param['name']
            param_type = param.get('type', 'String')
            is_linked_list = param.get('is_linked_list', False)

            if param_name in test_input:
                value = test_input[param_name]

                if is_linked_list:
                    arr_name = f"{param_name}Arr"
                    var_lines.append(f"int[] {arr_name} = {java_literal(value, 'int[]')};")
                    var_lines.append(f"ListNode {param_name} = arrayToList({arr_name});")
                else:
                    var_lines.append(f"{param_type} {param_name} = {java_literal(value, param_type)};")

                arg_names.append(param_name)
    else:
        # Single parameter case
        if parameters:
            param = parameters[0]
            param_name = param['name']
            param_type = param.get('type', 'String')
            var_lines.append(f"{param_type} {param_name} = {java_literal(test_input, param_type)};")
            arg_names.append(param_name)

    input_setup = "\n            ".join(var_lines)
    args_call = ", ".join(arg_names)

    # Build result handling code
    result_handling = ""
    if return_type == 'void':
        if returns_modified_input:
            result_handling = f"solution.{method_name}({args_call});\n            System.out.println(toJson({returns_modified_input}));"
        else:
            result_handling = f"solution.{method_name}({args_call});\n            System.out.println(\"null\");"
    elif return_type == 'int':
        result_handling = f"int result = solution.{method_name}({args_call});\n            System.out.println(result);"
    elif return_type == 'boolean':
        result_handling = f"boolean result = solution.{method_name}({args_call});\n            System.out.println(result ? \"true\" : \"false\");"
    elif return_type == 'int[]':
        result_handling = f"int[] result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_type == 'String[]':
        result_handling = f"String[] result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_type == 'int[][]':
        result_handling = f"int[][] result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_type == 'String[][]':
        result_handling = f"String[][] result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_type == 'String':
        result_handling = f"String result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_type == 'List<List<String>>':
        result_handling = f"List<List<String>> result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    elif return_is_linked_list:
        result_handling = f"ListNode result = solution.{method_name}({args_call});\n            System.out.println(toJson(result));"
    else:
        result_handling = f"Object result = solution.{method_name}({args_call});\n            System.out.println(result);"

    # Build ListNode-related methods only if needed
    listnode_methods = ""
    if uses_listnode:
        listnode_methods = """
    static String toJson(ListNode head) {
        if (head == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        ListNode cur = head;
        boolean first = true;
        while (cur != null) {
            if (!first) sb.append(",");
            first = false;
            sb.append(cur.val);
            cur = cur.next;
        }
        sb.append("]");
        return sb.toString();
    }

    static ListNode arrayToList(int[] arr) {
        if (arr == null || arr.length == 0) return null;
        ListNode dummy = new ListNode(0);
        ListNode tail = dummy;
        for (int val : arr) {
            tail.next = new ListNode(val);
            tail = tail.next;
        }
        return dummy.next;
    }
"""

    # Build test harness
    test_code = f"""
import java.util.*;

{helper_classes}

{code}

public class TestRunner {{
    static String toJson(int[] arr) {{
        if (arr == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) {{
            if (i > 0) sb.append(",");
            sb.append(arr[i]);
        }}
        sb.append("]");
        return sb.toString();
    }}

    static String toJson(boolean b) {{
        return b ? "true" : "false";
    }}

    static String toJson(String s) {{
        if (s == null) return "null";
        return "\\"" + s.replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"") + "\\"";
    }}

    static String toJson(char[][] board) {{
        if (board == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < board.length; i++) {{
            if (i > 0) sb.append(",");
            sb.append("[");
            for (int j = 0; j < board[i].length; j++) {{
                if (j > 0) sb.append(",");
                sb.append("\\"").append(board[i][j]).append("\\"");
            }}
            sb.append("]");
        }}
        sb.append("]");
        return sb.toString();
    }}

    static String toJson(String[] arr) {{
        if (arr == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) {{
            if (i > 0) sb.append(",");
            sb.append("\\"").append(arr[i].replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"")).append("\\"");
        }}
        sb.append("]");
        return sb.toString();
    }}

    static String toJson(int[][] arr) {{
        if (arr == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) {{
            if (i > 0) sb.append(",");
            sb.append("[");
            for (int j = 0; j < arr[i].length; j++) {{
                if (j > 0) sb.append(",");
                sb.append(arr[i][j]);
            }}
            sb.append("]");
        }}
        sb.append("]");
        return sb.toString();
    }}

    static String toJson(String[][] arr) {{
        if (arr == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) {{
            if (i > 0) sb.append(",");
            sb.append("[");
            for (int j = 0; j < arr[i].length; j++) {{
                if (j > 0) sb.append(",");
                sb.append("\\"").append(arr[i][j].replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"")).append("\\"");
            }}
            sb.append("]");
        }}
        sb.append("]");
        return sb.toString();
    }}

    static String toJson(List<List<String>> list) {{
        if (list == null) return "null";
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < list.size(); i++) {{
            if (i > 0) sb.append(",");
            sb.append("[");
            List<String> innerList = list.get(i);
            for (int j = 0; j < innerList.size(); j++) {{
                if (j > 0) sb.append(",");
                sb.append("\\"").append(innerList.get(j).replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"")).append("\\"");
            }}
            sb.append("]");
        }}
        sb.append("]");
        return sb.toString();
    }}
{listnode_methods}
    public static void main(String[] args) {{
        try {{
            {input_setup}

            Solution solution = new Solution();
            {result_handling}
        }} catch (Exception e) {{
            System.err.println("ERROR: " + e.getMessage());
            e.printStackTrace();
            System.exit(1);
        }}
    }}
}}
"""

    # Clean up any existing TestRunner files first
    temp_dir = tempfile.gettempdir()
    for file in os.listdir(temp_dir):
        if file.startswith('TestRunner') and (file.endswith('.java') or file.endswith('.class')):
            try:
                os.unlink(os.path.join(temp_dir, file))
            except:
                pass

    with tempfile.NamedTemporaryFile(mode='w', suffix='.java', delete=False) as f:
        f.write(test_code)
        temp_file = f.name

    java_file = os.path.join(os.path.dirname(temp_file), 'TestRunner.java')
    os.rename(temp_file, java_file)

    try:
        # Compile
        compile_result = subprocess.run(
            ['javac', java_file],
            capture_output=True,
            text=True,
            timeout=10
        )

        if compile_result.returncode != 0:
            return {
                'input': test_input,
                'expected': expected_output,
                'actual': None,
                'passed': False,
                'error': f'Compilation error: {compile_result.stderr}'
            }

        # Run
        class_dir = os.path.dirname(java_file)
        run_result = subprocess.run(
            ['java', '-cp', class_dir, 'TestRunner'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if run_result.returncode == 0:
            try:
                output_str = run_result.stdout.strip()

                # Parse output
                try:
                    actual_output = json.loads(output_str)
                except:
                    # Handle simple outputs like numbers
                    if output_str.isdigit() or (output_str.startswith('-') and output_str[1:].isdigit()):
                        actual_output = int(output_str)
                    elif output_str in ['true', 'false']:
                        actual_output = output_str == 'true'
                    else:
                        actual_output = output_str

                # Compare outputs
                is_correct = compare_outputs(actual_output, expected_output, comparison_strategy)

                return {
                    'input': test_input,
                    'expected': expected_output,
                    'actual': actual_output,
                    'passed': is_correct,
                    'error': None
                }
            except Exception as e:
                return {
                    'input': test_input,
                    'expected': expected_output,
                    'actual': run_result.stdout.strip(),
                    'passed': False,
                    'error': f'Output parsing error: {str(e)}'
                }
        else:
            return {
                'input': test_input,
                'expected': expected_output,
                'actual': None,
                'passed': False,
                'error': run_result.stderr.strip()
            }
    finally:
        # Clean up
        if os.path.exists(java_file):
            os.unlink(java_file)
        class_file = java_file.replace('.java', '.class')
        if os.path.exists(class_file):
            os.unlink(class_file)
        # Clean up any additional class files (for inner classes)
        class_dir = os.path.dirname(java_file)
        try:
            for file in os.listdir(class_dir):
                if file.startswith('TestRunner') and file.endswith('.class'):
                    os.unlink(os.path.join(class_dir, file))
        except:
            pass
        # Also clean up any TestRunner files in temp directory
        temp_dir = tempfile.gettempdir()
        try:
            for file in os.listdir(temp_dir):
                if file.startswith('TestRunner') and (file.endswith('.java') or file.endswith('.class')):
                    os.unlink(os.path.join(temp_dir, file))
        except:
            pass

def compare_outputs(actual, expected, comparison_strategy="exact"):
    """Compare actual output with expected output"""
    # Handle None/null cases
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False

    if comparison_strategy == "order_independent":
        # For arrays/lists where order doesn't matter
        if isinstance(actual, list) and isinstance(expected, list):
            # Handle nested lists (like Group Anagrams)
            if actual and expected and isinstance(actual[0], list) and isinstance(expected[0], list):
                # Sort each inner list and then sort the outer list
                actual_sorted = [sorted(inner) for inner in actual]
                expected_sorted = [sorted(inner) for inner in expected]
                return sorted(actual_sorted) == sorted(expected_sorted)
            else:
                # Handle simple lists
                return sorted(actual) == sorted(expected)
    
    # Generic deep equality
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
