"""Просмотр полей протокола, связанных реплик и полноты формы."""
from copy import deepcopy
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .model import AppError
from .protocol import BY_KEY, FIELDS, FORM_TITLE, STATUS_LABELS, set_field_value
from .protocol_export import FORM_SECTIONS, export_protocol_form
from .protocol_review import review_protocol
from .storage import export_protocol


class ProtocolWindow(tk.Toplevel):
    def __init__(self, parent, document, on_change, on_regenerate):
        super().__init__(parent)
        self.title("Проверка диалога и черновик протокола")
        self.geometry("1060x720")
        self.minsize(840, 570)
        self.transient(parent)
        self.document = document
        self.on_change = on_change
        self.on_regenerate = on_regenerate
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.title_label = ttk.Label(self, text=FORM_TITLE, style="Title.TLabel", wraplength=810)
        self.title_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 5))
        self.summary = tk.StringVar()
        self.summary_label = ttk.Label(self, textvariable=self.summary, wraplength=810)
        self.summary_label.grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.notice = tk.StringVar()
        self.notice_label = ttk.Label(self, textvariable=self.notice, style="Muted.TLabel", wraplength=810)
        self.notice_label.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 8))
        self.bind("<Configure>", self._resize)

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew", padx=14)
        questions = ttk.Frame(self.tabs, padding=8)
        self.follow_ups = ttk.Frame(self.tabs, padding=8)
        form = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(questions, text="Вопросы и ответы")
        self.tabs.add(self.follow_ups, text="Что уточнить")
        self.tabs.add(form, text="Форма протокола")

        for page in (questions, self.follow_ups, form):
            page.columnconfigure(0, weight=1)
            page.rowconfigure(0, weight=1)

        self.question_tree = self._table(questions, (
            ("number", "№", 42), ("field", "Поле протокола", 180),
            ("prompt", "Ожидаемый вопрос", 355), ("status", "Результат проверки", 220),
        ))
        self.question_detail = self._details(questions)
        self.question_tree.bind("<<TreeviewSelect>>", self._show_question)
        self.follow_up_text = tk.Text(self.follow_ups, wrap="word", state="disabled",
                                     font=("Segoe UI", 10), padx=12, pady=10)
        self.follow_up_text.grid(row=0, column=0, sticky="nsew")
        follow_scroll = ttk.Scrollbar(self.follow_ups, orient="vertical", command=self.follow_up_text.yview)
        follow_scroll.grid(row=0, column=1, sticky="ns")
        self.follow_up_text.configure(yscrollcommand=follow_scroll.set)

        self.tree = self._table(form, (
            ("field", "Раздел / поле", 270), ("status", "Состояние", 170),
            ("value", "Значение", 375),
        ))
        self.tree.tag_configure("section", background="#e6f0f1", foreground="#17343c",
                                font=("Segoe UI", 9, "bold"))
        self.tree.bind("<<TreeviewSelect>>", self._show_evidence)
        self.tree.bind("<Double-1>", lambda event: self._edit())
        self.detail = self._details(form)
        ttk.Button(form, text="Изменить выбранное поле…", command=self._edit).grid(
            row=2, column=0, sticky="w", pady=(0, 3))

        controls = ttk.Frame(self)
        controls.grid(row=4, column=0, sticky="ew", padx=14, pady=(10, 12))
        ttk.Button(controls, text="Вне протокола…", command=self._off_topic).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Разметить заново…", command=self._regenerate).pack(side="left", padx=(0, 12))
        for label, extension in (("Word", ".docx"), ("PDF", ".pdf"), ("TXT", ".txt")):
            ttk.Button(controls, text=f"Экспорт {label}…",
                       command=lambda suffix=extension: self._export(suffix)).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Закрыть", command=self.destroy).pack(side="right")
        self._refresh()
        self.tree.selection_set(FIELDS[0].key)
        self.grab_set()

    def _table(self, parent, columns):
        table = ttk.Frame(parent)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        tree = ttk.Treeview(table, columns=[key for key, _, _ in columns],
                            show="headings", selectmode="browse")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=min(width, 95), stretch=key in {"value", "prompt"})
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return tree

    def _details(self, parent):
        panel = ttk.Frame(parent)
        panel.grid(row=1, column=0, sticky="ew", pady=8)
        panel.columnconfigure(0, weight=1)
        body = tk.Text(panel, height=7, wrap="word", state="disabled",
                       font=("Segoe UI", 10), padx=7, pady=5)
        scroll = ttk.Scrollbar(panel, orient="vertical", command=body.yview)
        body.configure(yscrollcommand=scroll.set)
        body.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")
        return body

    def _resize(self, event):
        if event.widget is self:
            for label in (self.title_label, self.summary_label, self.notice_label):
                label.configure(wraplength=event.width - 28)

    def _refresh(self):
        draft = self.document.protocol
        review = review_protocol(draft)
        filled_pct = f"{review.filled_pct:.1f}".replace(".", ",")
        empty_pct = f"{review.empty_pct:.1f}".replace(".", ",")
        self.summary.set(
            f"Заполнено {review.filled} из {review.total} ({filled_pct}%)  ·  "
            f"Без значения {review.empty} из {review.total} ({empty_pct}%)  ·  "
            f"Вопросов найдено {review.questions_found} из {review.question_count}"
        )
        notices = [review.question_source]
        if draft["source_text"] != self.document.text:
            notices.append("Расшифровка изменена. Обновите разметку перед экспортом.")
        notices.extend(draft["warnings"])
        self.notice.set(" ".join(notices))

        self._questions = {str(row.number): row for row in review.questions}
        for key in self.question_tree.get_children():
            if key not in self._questions:
                self.question_tree.delete(key)
        for key, row in self._questions.items():
            status = row.status + (" · вне порядка" if row.order_mismatch else "")
            values = (row.number, BY_KEY[row.field_key].label, row.prompt, status)
            self._upsert(self.question_tree, key, values)
        if self._questions and not self.question_tree.selection():
            self.question_tree.selection_set(next(iter(self._questions)))
        self._show_question()

        questions_to_ask = [row.prompt for row in review.questions if row.follow_up]
        follow_up = "\n\n".join(f"{index}. {prompt}" for index, prompt in enumerate(questions_to_ask, 1))
        self._replace_text(self.follow_up_text, follow_up or "Уточнений по текущей проверке нет.")

        for index, (section, fields) in enumerate(FORM_SECTIONS):
            if section != BY_KEY[fields[0]].label:
                self._upsert(self.tree, f"section:{index}", (section, "", ""), ("section",))
            for key in fields:
                field = BY_KEY[key]
                item = draft["fields"][key]
                value = item["value"].replace("\n", " / ")
                if value and field.unit:
                    value += " " + field.unit
                self._upsert(self.tree, key, (field.label, STATUS_LABELS[item["status"]], value))
        self._show_evidence()

    def _upsert(self, tree, key, values, tags=()):
        if tree.exists(key):
            tree.item(key, values=values)
        else:
            tree.insert("", "end", iid=key, values=values, tags=tags)

    def _replace_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _show_question(self, event=None):
        selection = self.question_tree.selection()
        row = self._questions.get(selection[0]) if selection else None
        if row is None:
            self._replace_text(self.question_detail, "")
            return
        detail = [
            "По чек-листу — " + row.prompt,
            "В разговоре — " + (row.asked or "вопрос не найден"),
            "Ответ — " + (row.answer or "ответ не найден"),
        ]
        if row.follow_up:
            detail.append("Уточнить — " + row.follow_up)
        if row.order_mismatch:
            detail.append("Вопрос прозвучал в другой последовательности относительно учебного чек-листа.")
        self._replace_text(self.question_detail, "\n".join(detail))

    def _show_evidence(self, event=None):
        selected = self.tree.selection()
        item = self.document.protocol["fields"].get(selected[0]) if selected else None
        lines = []
        if item is not None:
            if item["value"]:
                lines.extend(["Значение — " + item["value"], ""])
            for pair in item["evidence"]:
                if pair["question"]:
                    lines.append("Вопрос — " + pair["question"])
                if pair["answer"]:
                    lines.append("Источник — " + pair["answer"])
            if not item["evidence"]:
                lines.append("Связанных реплик нет.")
        self._replace_text(self.detail, "\n".join(lines))

    def _edit(self):
        selected = self.tree.selection()
        if not selected or selected[0] not in BY_KEY:
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

    def _export(self, extension):
        label = {".docx": "Документ Word", ".pdf": "Документ PDF", ".txt": "Текст UTF-8"}[extension]
        path = filedialog.asksaveasfilename(parent=self, title="Экспорт черновика протокола",
                    initialfile="protocol-draft" + extension, defaultextension=extension,
                    filetypes=[(label, "*" + extension)])
        if path:
            try:
                if extension == ".txt":
                    export_protocol(self.document, path)
                else:
                    export_protocol_form(self.document, path)
            except AppError as exc:
                messagebox.showerror("Протокол не экспортирован", str(exc), parent=self)
