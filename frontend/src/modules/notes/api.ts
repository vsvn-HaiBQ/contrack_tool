import { http } from "../../shared/http";
import type { Note } from "../../shared/types";

export const notesApi = {
  list(): Promise<Note[]> {
    return http<Note[]>("/notes");
  },
  create(payload: { title: string; content: string }): Promise<Note> {
    return http<Note>("/notes", { method: "POST", body: JSON.stringify(payload) });
  },
  update(id: number, payload: { title: string; content: string }): Promise<Note> {
    return http<Note>(`/notes/${id}`, { method: "PUT", body: JSON.stringify(payload) });
  },
  delete(id: number): Promise<void> {
    return http<void>(`/notes/${id}`, { method: "DELETE" });
  },
  toggleLock(id: number): Promise<Note> {
    return http<Note>(`/notes/${id}/lock`, { method: "PATCH" });
  },
  reorder(ids: number[]): Promise<Note[]> {
    return http<Note[]>("/notes/reorder", { method: "PATCH", body: JSON.stringify({ ids }) });
  },
};
