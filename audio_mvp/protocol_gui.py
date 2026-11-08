"""Просмотр полей протокола, связанных реплик и полноты формы."""
from copy import deepcopy
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .model import AppError
from .protocol import BY_KEY, FIELDS, FORM_TITLE, STATUS_LABELS, incomplete_required, set_field_value
from .storage import export_protocol


class ProtocolWindow(tk.Toplevel):
    def __init__(self, parent, document, on_change, on_regenerate):
        super().__init__(parent)
        self.title("Черновик протокола")
        self.geometry("960x690")
        self.minsize(710, 500)
        self.transient(parent)
        self.document = document
        self.on_change = on_change
        self.on_regenerate = on_regenerate
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=FORM_TITLE, style="Title.TLabel", wraplength=670).grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 5))
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, wraplength=675).grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.bind("<Configure>", self._resize)

        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky="nsew", padx=14)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("field", "status", "value"),
                                 show="headings", selectmode="browse")
        for key, label, width in (("field", "Поле", 220), ("status", "Состояние", 155),
                                  ("value", "Значение", 280)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=95, stretch=key == "value")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._show_evidence)
        self.tree.bind("<Double-1>", lambda event: self._edit())

        self.detail = tk.Text(self, height=7, wrap="word", state="disabled",
                              font=("Segoe UI", 10), padx=7, pady=5)
        self.detail.grid(row=3, column=0, sticky="ew", padx=14, pady=8)
        controls = ttk.Frame(self)
        controls.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 12))
        ttk.Button(controls, text="Изменить поле…", command=self._edit).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Вне протокола…", command=self._off_topic).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Разметить заново…", command=self._regenerate).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Экспорт протокола…", command=self._export).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Закрыть", command=self.destroy).pack(side="right")
        self._refresh()
        self.tree.selection_set(FIELDS[0].key)
        self.grab_set()

    def _resize(self, event):
        if event.widget is self:
            self.grid_slaves(row=1, column=0)[0].configure(wraplength=event.width - 28)

    def _refresh(self):
        draft = self.document.protocol
        missing = incomplete_required(draft)
        pending = sum(not item["value"] for item in draft["fields"].values())
        coverage = sum(any(row["question"] for row in item["evidence"]) for item in draft["fields"].values())
        status = f"Полей с привязанными вопросами: {coverage}. Полей без значения: {pending}. "
        status += "Уточнить для учебного минимума: " + ", ".join(missing) + "." if missing else (
            "Учебный минимум заполнен. Сверьте значения с записью.")
        if draft["source_text"] != self.document.text:
            status = "Расшифровка изменена. Обновите разметку перед экспортом. " + status
        if draft["warnings"]:
            status += " " + " ".join(draft["warnings"])
        self.summary.set(status)
        for field in FIELDS:
            item = draft["fields"][field.key]
            value = item["value"].replace("\n", " / ")
            if value and field.unit:
                value += " " + field.unit
            values = (field.label + (" *" if field.required else ""), STATUS_LABELS[item["status"]], value)
            if self.tree.exists(field.key):
                self.tree.item(field.key, values=values)
            else:
                self.tree.insert("", "end", iid=field.key, values=values)
        self._show_evidence()

    def _show_evidence(self, event=None):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        selected = self.tree.selection()
        if selected:
            item = self.document.protocol["fields"][selected[0]]
            if item["value"]:
                self.detail.insert("end", "Значение: " + item["value"] + "\n\n")
            for pair in item["evidence"]:
                if pair["question"]:
                    self.detail.insert("end", "Вопрос: " + pair["question"] + "\n")
                if pair["answer"]:
                    self.detail.insert("end", "Источник: " + pair["answer"] + "\n")
            if not item["evidence"]:
                self.detail.insert("end", "Связанных реплик нет.")
        self.detail.configure(state="disabled")

    def _edit(self):
        selected = self.tree.selection()
        if not selected:
            return
        key = selected[0]
        field = BY_KEY[key]
        window = tk.Toplevel(self)
        window.title(field.label)
        window.transient(self)
        editor = tk.Text(window, width=58, height=7, wrap="word", font=("Segoe UI", 11))
        ttk.Label(window, text=field.label + (f" ({field.unit})" if field.unit else "")).pack(
            anchor="w", padx=12, pady=(12, 4))
        editor.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        editor.insert("1.0", self.document.protocol["fields"][key]["value"])

        def close():
            window.destroy()
            self.grab_set()

        def apply():
            draft = deepcopy(self.document.protocol)
            try:
                set_field_value(draft, key, editor.get("1.0", "end-1c"))
                self.on_change(draft)
            except AppError as exc:
                messagebox.showerror("Поле не изменено", str(exc), parent=window)
                return
            close()
            self._refresh()

        ttk.Button(window, text="Применить", command=apply).pack(pady=(2, 10))
        window.protocol("WM_DELETE_WINDOW", close)
        window.grab_set()
        editor.focus_set()

    def _off_topic(self):
        window = tk.Toplevel(self)
        window.title("Реплики вне протокола")
        window.transient(self)
        body = tk.Text(window, width=76, height=14, wrap="word", font=("Segoe UI", 11))
        body.pack(fill="both", expand=True, padx=10, pady=10)
        rows = self.document.protocol["off_topic"]
        body.insert("1.0", "\n\n".join("\n".join(filter(None, row.values())) for row in rows)
                    if rows else "Модель не выделила реплик вне протокола.")
        body.configure(state="disabled")

        def close():
            window.destroy()
            self.grab_set()

        window.protocol("WM_DELETE_WINDOW", close)
        window.grab_set()

    def _regenerate(self):
        if messagebox.askyesno("Разметить заново",
                                "Новая разметка заменит текущий черновик и его ручные правки. Продолжить?",
                                parent=self):
            self.destroy()
            self.on_regenerate()

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self, title="Экспорт черновика протокола",
                    initialfile="protocol-draft.txt", defaultextension=".txt", filetypes=[("Текст UTF-8", "*.txt")])
        if path:
            try:
                export_protocol(self.document, path)
            except AppError as exc:
                messagebox.showerror("Протокол не экспортирован", str(exc), parent=self)
