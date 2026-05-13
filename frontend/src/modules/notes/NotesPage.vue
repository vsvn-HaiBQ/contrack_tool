<script setup lang="ts">
import { ref, computed, watch } from "vue";
import "quill/dist/quill.snow.css";
import { notesApi } from "./api";
import { sessionState } from "../../shared/session";
import type { Note } from "../../shared/types";

const notes = ref<Note[]>([]);
const loading = ref(false);
const isAdmin = computed(() => sessionState.me?.role === "admin");

// ── Modal ────────────────────────────────────────────────────────────────────
const showModal = ref(false);
const editingNote = ref<Note | null>(null);
const formTitle = ref("");
const formContent = ref("");

// ── Quill ────────────────────────────────────────────────────────────────────
let quillInstance: import("quill").default | null = null;
const editorContainer = ref<HTMLDivElement | null>(null);

watch(showModal, async (val) => {
  if (!val) {
    quillInstance = null;
    return;
  }
  const { default: Quill } = await import("quill");
  // nextTick inside watch(showModal) — wait for modal DOM
  await new Promise<void>((r) => setTimeout(r, 0));
  if (!editorContainer.value) return;
  quillInstance = new Quill(editorContainer.value, {
    theme: "snow",
    modules: {
      toolbar: [
        [{ font: [] }, { size: ["small", false, "large", "huge"] }],
        [{ header: [1, 2, 3, 4, 5, 6, false] }],
        ["bold", "italic", "underline", "strike"],
        [{ color: [] }, { background: [] }],
        [{ script: "sub" }, { script: "super" }],
        [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
        [{ align: [] }],
        ["blockquote", "code-block"],
        ["link", "image"],
        ["clean"],
      ],
    },
  });
  quillInstance.on("text-change", () => {
    formContent.value = quillInstance!.getSemanticHTML();
  });
  if (formContent.value) {
    const delta = quillInstance.clipboard.convert({ html: formContent.value });
    quillInstance.setContents(delta, "silent");
  }
});

// ── SortableJS — watch the ref so it triggers after notes load ───────────────
const listContainer = ref<HTMLElement | null>(null);
let sortableDestroy: (() => void) | null = null;

watch(listContainer, async (el) => {
  if (sortableDestroy) { sortableDestroy(); sortableDestroy = null; }
  if (!el) return;
  const Sortable = (await import("sortablejs")).default;
  const instance = Sortable.create(el, {
    handle: ".drag-handle",
    animation: 150,
    ghostClass: "sortable-ghost",
    onEnd: async (evt) => {
      const { oldIndex, newIndex } = evt;
      if (oldIndex === undefined || newIndex === undefined || oldIndex === newIndex) return;
      const moved = notes.value.splice(oldIndex, 1)[0];
      notes.value.splice(newIndex, 0, moved);
      await notesApi.reorder(notes.value.map((n) => n.id));
    },
  });
  sortableDestroy = () => instance.destroy();
}, { flush: "post" });

// ── Notes CRUD ───────────────────────────────────────────────────────────────
async function loadNotes() {
  loading.value = true;
  try { notes.value = await notesApi.list(); }
  finally { loading.value = false; }
}
loadNotes();

function openCreate() {
  editingNote.value = null;
  formTitle.value = "";
  formContent.value = "";
  showModal.value = true;
}

function openEdit(note: Note) {
  editingNote.value = note;
  formTitle.value = note.title;
  formContent.value = note.content;
  showModal.value = true;
}

function closeModal() {
  showModal.value = false;
  editingNote.value = null;
  formTitle.value = "";
  formContent.value = "";
}

async function saveNote() {
  if (!formTitle.value.trim()) return;
  if (editingNote.value) {
    const updated = await notesApi.update(editingNote.value.id, {
      title: formTitle.value,
      content: formContent.value,
    });
    const idx = notes.value.findIndex((n) => n.id === updated.id);
    if (idx !== -1) notes.value[idx] = updated;
  } else {
    const created = await notesApi.create({ title: formTitle.value, content: formContent.value });
    notes.value.push(created);
  }
  closeModal();
}

async function deleteNote(id: number) {
  if (!confirm("Delete this note?")) return;
  await notesApi.delete(id);
  notes.value = notes.value.filter((n) => n.id !== id);
}

async function toggleLock(note: Note) {
  const updated = await notesApi.toggleLock(note.id);
  const idx = notes.value.findIndex((n) => n.id === note.id);
  if (idx !== -1) notes.value[idx] = updated;
}

// ── Collapse (default collapsed) ────────────────────────────────────────────
const expanded = ref<Record<number, boolean>>({});
function toggleExpand(id: number) {
  expanded.value[id] = !expanded.value[id];
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-[#D0D1D2] px-6 py-4">
      <h1 class="text-xl font-semibold text-[#171A20]">Notes</h1>
      <button
        class="flex items-center gap-1.5 rounded bg-[#3E6AE1] px-4 py-2 text-sm text-white transition hover:bg-[#2f55c4]"
        @click="openCreate"
      >
        <!-- plus icon -->
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New Note
      </button>
    </div>

    <!-- Notes list -->
    <div class="flex-1 overflow-y-auto p-6">
      <div v-if="loading" class="text-sm text-[#9EA0A5]">Loading...</div>
      <div v-else-if="notes.length === 0" class="text-sm text-[#9EA0A5]">No notes yet.</div>

      <div v-else ref="listContainer" class="flex flex-col gap-3">
        <div
          v-for="note in notes"
          :key="note.id"
          class="rounded-lg border border-[#D0D1D2] bg-white shadow-sm"
        >
          <!-- Note header row -->
          <div class="flex items-center gap-1.5 px-3 py-2.5">
            <!-- Drag handle (admin only) -->
            <span
              v-if="isAdmin"
              class="drag-handle mr-1 cursor-grab select-none text-[#C4C5C7] hover:text-[#393C41]"
              title="Drag to reorder"
              @click.stop
            >
              <!-- 6-dot drag icon -->
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="9" cy="5" r="2"/><circle cx="15" cy="5" r="2"/>
                <circle cx="9" cy="12" r="2"/><circle cx="15" cy="12" r="2"/>
                <circle cx="9" cy="19" r="2"/><circle cx="15" cy="19" r="2"/>
              </svg>
            </span>

            <!-- Title (click to expand/collapse) -->
            <button
              class="flex flex-1 items-center gap-2 text-left font-medium text-[#171A20] hover:text-[#3E6AE1]"
              @click="toggleExpand(note.id)"
            >
              <span class="flex-1">{{ note.title }}</span>
              <!-- chevron -->
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9EA0A5" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 transition-transform duration-150" :style="expanded[note.id] ? 'transform:rotate(180deg)' : ''">
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </button>

            <!-- Action icons -->
            <div class="flex items-center gap-0.5">
              <!-- Lock / Unlock toggle (admin only) -->
              <button
                v-if="isAdmin"
                class="rounded p-1.5 text-[#9EA0A5] transition hover:bg-[#EFF0F1]"
                :class="note.locked ? 'text-[#F59E0B]' : 'text-[#9EA0A5]'"
                :title="note.locked ? 'Unlock' : 'Lock'"
                @click.stop="toggleLock(note)"
              >
                <!-- Lock closed icon -->
                <svg v-if="note.locked" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <!-- Lock open icon -->
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>
                </svg>
              </button>

              <!-- Edit (hidden if locked & not admin) -->
              <button
                v-if="!note.locked || isAdmin"
                class="rounded p-1.5 text-[#3E6AE1] transition hover:bg-[#EBF0FC]"
                title="Edit"
                @click.stop="openEdit(note)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </button>

              <!-- Delete (hidden if locked & not admin) -->
              <button
                v-if="!note.locked || isAdmin"
                class="rounded p-1.5 text-red-500 transition hover:bg-[#FEF2F2]"
                title="Delete"
                @click.stop="deleteNote(note.id)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                  <path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Note content (collapsed by default) -->
          <div v-if="expanded[note.id]" class="border-t border-[#EFF0F1] px-5 py-4">
            <div class="ql-content" v-html="note.content"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal overlay -->
    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/40" @click="closeModal"></div>

      <div class="relative z-10 flex w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl" style="max-height: 90vh;">
        <!-- Modal header -->
        <div class="flex items-center justify-between border-b border-[#D0D1D2] px-5 py-4">
          <h2 class="text-lg font-semibold text-[#171A20]">{{ editingNote ? 'Edit Note' : 'New Note' }}</h2>
          <button class="rounded p-1 text-[#9EA0A5] transition hover:bg-[#EFF0F1] hover:text-[#393C41]" @click="closeModal">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        <!-- Modal body -->
        <div class="flex flex-col gap-4 overflow-y-auto p-5">
          <div class="grid gap-1">
            <label class="text-sm font-medium text-[#393C41]">Title</label>
            <input
              v-model="formTitle"
              class="rounded border border-[#D0D1D2] px-3 py-2 text-[#171A20] outline-none transition focus:border-[#3E6AE1]"
              placeholder="Enter title..."
              maxlength="500"
            />
          </div>
          <div class="grid gap-1">
            <label class="text-sm font-medium text-[#393C41]">Content</label>
            <div ref="editorContainer"></div>
          </div>
        </div>

        <!-- Modal footer -->
        <div class="flex justify-end gap-2 border-t border-[#D0D1D2] px-5 py-4">
          <button class="rounded border border-[#D0D1D2] px-4 py-2 text-sm text-[#393C41] transition hover:bg-[#EFF0F1]" @click="closeModal">
            Cancel
          </button>
          <button class="rounded bg-[#3E6AE1] px-4 py-2 text-sm text-white transition hover:bg-[#2f55c4]" @click="saveNote">
            Save
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* ── Quill editor in modal ────────────────────────────────────────────────── */
.ql-toolbar.ql-snow {
  border-color: #D0D1D2;
  border-top-left-radius: 6px;
  border-top-right-radius: 6px;
  font-family: inherit;
}
.ql-container.ql-snow {
  border-color: #D0D1D2;
  border-bottom-left-radius: 6px;
  border-bottom-right-radius: 6px;
  font-family: inherit;
  font-size: 14px;
}
.ql-editor {
  min-height: 200px;
  max-height: 40vh;
  overflow-y: auto;
}

/* ── Quill content rendered in note cards ─────────────────────────────────── */
.ql-content { font-size: 14px; line-height: 1.65; color: #393C41; }
.ql-content p:last-child { margin-bottom: 0; }
.ql-content h1 { font-size: 1.5em; font-weight: 700; margin: 0.75em 0 0.35em; }
.ql-content h2 { font-size: 1.25em; font-weight: 700; margin: 0.75em 0 0.35em; }
.ql-content h3 { font-size: 1.1em; font-weight: 700; margin: 0.75em 0 0.35em; }
.ql-content h4, .ql-content h5, .ql-content h6 { font-size: 1em; font-weight: 700; margin: 0.5em 0 0.25em; }
.ql-content ul, .ql-content ol { padding-left: 1.75em; margin: 0.35em 0; }
.ql-content li { margin: 0.2em 0; }
.ql-content a { color: #3E6AE1; text-decoration: underline; }
.ql-content strong { font-weight: 700; }
.ql-content em { font-style: italic; }
.ql-content s { text-decoration: line-through; }
.ql-content blockquote { border-left: 3px solid #D0D1D2; margin: 0.5em 0; padding: 0.25em 0 0.25em 1em; color: #6B6E72; font-style: italic; }
.ql-content pre { background: #F4F5F6; border-radius: 6px; padding: 0.75em 1em; font-size: 13px; overflow-x: auto; margin: 0.5em 0; }
.ql-content code { background: #F4F5F6; border-radius: 3px; padding: 0.1em 0.35em; font-size: 13px; }
.ql-content .ql-align-center { text-align: center; }
.ql-content .ql-align-right { text-align: right; }
.ql-content .ql-align-justify { text-align: justify; }
.ql-content sub { vertical-align: sub; font-size: smaller; }
.ql-content sup { vertical-align: super; font-size: smaller; }

/* ── SortableJS drag ghost ────────────────────────────────────────────────── */
.sortable-ghost {
  opacity: 0.4;
  background: #EFF0F1;
  border-radius: 8px;
}
</style>
