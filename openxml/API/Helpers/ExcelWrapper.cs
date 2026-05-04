using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using System.Text;
using Drawing = DocumentFormat.OpenXml.Drawing;
using Spreadsheet = DocumentFormat.OpenXml.Spreadsheet;

namespace API.Helpers
{
    public static class ExcelWrapper
    {
        public static void LogTree(string filePath, OpenXmlElement element, string text = "")
        {
            foreach (var item in element.ChildElements)
            {
                string typeName = item.GetType().Name;
                if (item is Spreadsheet.Text) typeName += "\t" + "\"" + (item as Spreadsheet.Text)!.Text + "\"";
                File.AppendAllText(filePath, text + typeName + "\n");
                LogTree(filePath, item, text + "\t");
            }
        }

        public static List<string> GetWords(Stream filePath, List<string> sheets)
        {
            List<string> words = new List<string>();
            List<Spreadsheet.SharedStringItem> includeSharedStrings = new List<Spreadsheet.SharedStringItem>();

            using (SpreadsheetDocument spreadsheet = SpreadsheetDocument.Open(filePath, false))
            {
                foreach (Spreadsheet.Sheet sheet in spreadsheet.WorkbookPart!.Workbook.Sheets!)
                {
                    if (sheet.Name == null || string.IsNullOrEmpty(sheet.Name.Value) || (sheet.State != null && sheet.State != Spreadsheet.SheetStateValues.Visible)) continue;
                    if (sheets.Count > 0 && !sheets.Contains(sheet.Name.Value)) continue;
                    WorksheetPart wsPart = (WorksheetPart)spreadsheet.WorkbookPart!.GetPartById(sheet.Id!);
                    foreach (Spreadsheet.Cell cell in wsPart.Worksheet.Descendants<Spreadsheet.Cell>())
                    {
                        if (cell == null || cell.InnerText.Length <= 0 || cell.DataType == null || cell.DataType.Value != Spreadsheet.CellValues.SharedString) continue;
                        foreach (SharedStringTablePart stringTablePart in spreadsheet.WorkbookPart.GetPartsOfType<SharedStringTablePart>())
                        {
                            if (stringTablePart == null) continue;
                            Spreadsheet.SharedStringItem stringItem = stringTablePart.SharedStringTable.Elements<Spreadsheet.SharedStringItem>().ElementAt(int.Parse(cell.InnerText));
                            if (includeSharedStrings.Contains(stringItem)) continue;
                            includeSharedStrings.Add(stringItem);
                            stringItem.RemoveAllChildren<Spreadsheet.PhoneticRun>();
                            stringItem.RemoveAllChildren<Spreadsheet.PhoneticProperties>();
                            foreach (string text in stringItem.InnerText.Split("\n"))
                            {
                                words.Add(text);
                            }
                        }
                    }
                    if (wsPart.DrawingsPart != null)
                    {
                        StringBuilder word = new StringBuilder();
                        foreach (var worksheetDrawing in wsPart.DrawingsPart.WorksheetDrawing)
                        {
                            if (!worksheetDrawing.Descendants<Drawing.Text>().Any()) continue;
                            foreach (Drawing.Paragraph paragraph in worksheetDrawing.Descendants<Drawing.Paragraph>())
                            {
                                if (!paragraph.Descendants<Drawing.Text>().Any()) continue;
                                foreach (OpenXmlElement element in paragraph.Elements())
                                {
                                    if (element is Drawing.Run)
                                    {
                                        foreach (Drawing.Text text in element.Descendants<Drawing.Text>())
                                        {
                                            word.Append(text.Text);
                                        }
                                    } else if (word.Length > 0)
                                    {
                                        words.Add(word.ToString());
                                        word.Clear();
                                    }
                                }
                                if (word.Length > 0)
                                {
                                    words.Add(word.ToString());
                                    word.Clear();
                                }
                            }
                        }
                    }
                    if (wsPart.WorksheetCommentsPart != null)
                    {
                        foreach (Spreadsheet.Comment comment in wsPart.WorksheetCommentsPart.Comments.Descendants<Spreadsheet.Comment>())
                        {
                            foreach (Spreadsheet.Text text in comment.Descendants<Spreadsheet.Text>())
                            {
                                foreach (string textSplit in text.Text.Split("\n"))
                                {
                                    words.Add(textSplit);
                                }
                            }
                        }
                    }
                }
                return words;
            }
        }

        public static void Translate(string filePath, Queue<string> trans, List<string> sheets)
        {
            List<Spreadsheet.SharedStringItem> includeSharedStrings = new List<Spreadsheet.SharedStringItem>();

            using (SpreadsheetDocument spreadsheet = SpreadsheetDocument.Open(filePath, true))
            {
                foreach (Spreadsheet.Sheet sheet in spreadsheet.WorkbookPart!.Workbook.Sheets!)
                {
                    if (sheet.Name == null || string.IsNullOrEmpty(sheet.Name.Value) || (sheet.State != null && sheet.State != Spreadsheet.SheetStateValues.Visible)) continue;
                    if (sheets.Count > 0 && !sheets.Contains(sheet.Name.Value)) continue;
                    WorksheetPart wsPart = (WorksheetPart)spreadsheet.WorkbookPart!.GetPartById(sheet.Id!);
                    foreach (Spreadsheet.Cell cell in wsPart.Worksheet.Descendants<Spreadsheet.Cell>())
                    {
                        if (cell == null || cell.InnerText.Length <= 0 || cell.DataType == null || cell.DataType.Value != Spreadsheet.CellValues.SharedString) continue;
                        foreach (SharedStringTablePart stringTablePart in spreadsheet.WorkbookPart.GetPartsOfType<SharedStringTablePart>())
                        {
                            if (stringTablePart == null) continue;
                            Spreadsheet.SharedStringItem stringItem = stringTablePart.SharedStringTable.Elements<Spreadsheet.SharedStringItem>().ElementAt(int.Parse(cell.InnerText));
                            if (includeSharedStrings.Contains(stringItem)) continue;
                            includeSharedStrings.Add(stringItem);
                            stringItem.RemoveAllChildren<Spreadsheet.PhoneticRun>();
                            stringItem.RemoveAllChildren<Spreadsheet.PhoneticProperties>();
                            string text = string.Empty;
                            foreach (string item in stringItem.InnerText.Split("\n"))
                            {
                                if (trans.Count > 0) text += "\n" + trans.Dequeue();
                            }
                            stringItem.RemoveAllChildren();
                            stringItem.Text = new Spreadsheet.Text(text);
                        }
                    }
                    if (wsPart.DrawingsPart != null)
                    {
                        StringBuilder word = new StringBuilder();
                        foreach (var worksheetDrawing in wsPart.DrawingsPart.WorksheetDrawing)
                        {
                            if (!worksheetDrawing.Descendants<Drawing.Text>().Any()) continue;
                            bool breakChecking = true;
                            foreach (Drawing.Paragraph paragraph in worksheetDrawing.Descendants<Drawing.Paragraph>())
                            {
                                if (!paragraph.Descendants<Drawing.Text>().Any()) continue;
                                foreach (OpenXmlElement element in paragraph.Elements())
                                {
                                    if (element is Drawing.Run)
                                    {
                                        if (breakChecking && word.Length == 0 && trans.Count > 0)
                                        {
                                            string data = trans.Dequeue();
                                            if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@";
                                            word.Append(data);
                                        }
                                        foreach (Drawing.Text text in element.Descendants<Drawing.Text>())
                                        {
                                            if (string.IsNullOrEmpty(text.Text)) continue;
                                            text.Text = word.ToString() == "@@@This_is_the_empty_replace@@@" ? "" : word.ToString();
                                            word.Clear();
                                        }
                                        breakChecking = false;
                                    }
                                    else breakChecking = true;
                                }
                                breakChecking = true;
                            }
                        }
                    }
                    if (wsPart.WorksheetCommentsPart != null)
                    {
                        foreach (Spreadsheet.Comment comment in wsPart.WorksheetCommentsPart.Comments.Descendants<Spreadsheet.Comment>())
                        {
                            foreach (Spreadsheet.Text text in comment.Descendants<Spreadsheet.Text>())
                            {
                                string newText = string.Empty;
                                foreach (string item in text.Text.Split("\n"))
                                {
                                    if (trans.Count > 0) newText += "\n" + trans.Dequeue();
                                }
                                text.Text = newText;
                            }
                        }
                    }
                }
                spreadsheet.Save();
            }
        }

        public static List<string> SheetNames(Stream filePath)
        {
            List<string> sheetNames = new List<string>();
            using (SpreadsheetDocument spreadsheet = SpreadsheetDocument.Open(filePath, false))
            {
                foreach (Spreadsheet.Sheet sheet in spreadsheet.WorkbookPart!.Workbook.Sheets!)
                {
                    if ((sheet.State == null || sheet.State == Spreadsheet.SheetStateValues.Visible) && sheet.Name != null && !string.IsNullOrEmpty(sheet.Name.Value))
                    {
                        sheetNames.Add(sheet.Name.Value);
                    }
                }
            }
            return sheetNames;
        }
    }
}
