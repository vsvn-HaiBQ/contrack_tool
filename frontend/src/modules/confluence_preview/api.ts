import { http } from "../../shared/http";

export type ConfluencePreviewResult = {
  file_name: string;
  title: string;
  html: string;
};

export const confluencePreviewApi = {
  preview: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return http<ConfluencePreviewResult>("/confluence-preview", {
      method: "POST",
      body
    });
  }
};
