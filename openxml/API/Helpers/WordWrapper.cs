using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using System.Text;

namespace API.Helpers
{
    public static class WordWrapper
    {
        public static void LogTree(string filePath, OpenXmlElement element, string text = "")
        {
            foreach (var item in element.ChildElements)
            {
                string typeName = item.GetType().Name;
                if (item is Text) typeName += "\t" + "\"" + (item as Text)!.Text + "\"";
                File.AppendAllText(filePath, text + typeName + "\n");
                LogTree(filePath, item, text + "\t");
            }
        }

        public static List<string> GetWords(Stream filePath)
        {
            using (WordprocessingDocument wdDoc = WordprocessingDocument.Open(filePath, false))
            {
                List<string> words = new();
                List<Run> runInstances = new();

                //foreach (HeaderPart headerPart in wdDoc.MainDocumentPart?.HeaderParts!)
                //{
                //    GetText(headerPart.Header, words, runInstances);
                //}

                Body body = wdDoc.MainDocumentPart?.Document.Body!;
                GetText(body, words, runInstances);

                //foreach (FooterPart footerPart in wdDoc.MainDocumentPart?.FooterParts!)
                //{
                //    GetText(footerPart.Footer, words, runInstances);
                //}

                FootnotesPart? footnotesPart = wdDoc.MainDocumentPart?.FootnotesPart;
                if (footnotesPart != null)
                {
                    GetText(footnotesPart.Footnotes, words, runInstances);
                }

                return words;
            }
        }

        public static void GetText(OpenXmlElement element, List<string> words, List<Run> runInstances)
        {
            StringBuilder word = new();
            foreach (Paragraph paragraph in element.Descendants<Paragraph>())
            {
                foreach (OpenXmlElement runOrHyperLink in paragraph.Elements())
                {
                    if (runOrHyperLink is Hyperlink)
                    {
                        foreach (Run run in runOrHyperLink.Elements<Run>())
                        {
                            HandleGetTextRun(run, word, words, runInstances);
                        }
                    }
                    else if (runOrHyperLink is Run)
                    {
                        HandleGetTextRun((Run)runOrHyperLink, word, words, runInstances);
                    }
                }
                if (word.Length > 0) words.Add(word.ToString());
                word.Clear();
            }
        }

        public static void HandleGetTextRun(Run run, StringBuilder word, List<string> words, List<Run> runInstances)
        {
            if (runInstances.Contains(run)) return;
            runInstances.Add(run);
            if (!run.Elements<Text>().Any() && (run.Descendants<TabChar>().Any() || run.Descendants<Text>().Any()))
            {
                if (word.Length > 0) words.Add(word.ToString());
                word.Clear();
                GetText(run, words, runInstances);
            }
            else
            {
                foreach (var item in run.ChildElements)
                {
                    if (item is TabChar)
                    {
                        if (word.Length > 0) words.Add(word.ToString());
                        word.Clear();
                    }
                    else if (item is Text)
                    {
                        word.Append(((Text)item).Text);
                    }
                }
            }
        }

        public static void Translate(string filePath, Queue<string> trans)
        {
            using (WordprocessingDocument wdDoc = WordprocessingDocument.Open(filePath, true))
            {
                StringBuilder word = new();
                List<Run> runInstance = new();

                //foreach (HeaderPart headerPart in wdDoc.MainDocumentPart?.HeaderParts!)
                //{
                //    ReplaceText(headerPart.Header, trans, runInstance, word);
                //}

                Body body = wdDoc.MainDocumentPart?.Document.Body!;
                ReplaceText(body, trans, runInstance, word);

                //foreach (FooterPart footerPart in wdDoc.MainDocumentPart?.FooterParts!)
                //{
                //    ReplaceText(footerPart.Footer, trans, runInstance, word);
                //}

                FootnotesPart? footnotesPart = wdDoc.MainDocumentPart?.FootnotesPart;
                if (footnotesPart != null)
                {
                    ReplaceText(footnotesPart.Footnotes, trans, runInstance, word);
                }

                wdDoc.Save();
            }
        }

        public static void ReplaceText(OpenXmlElement element, Queue<string> words, List<Run> runInstances, StringBuilder word)
        {
            foreach (Paragraph paragraph in element.Descendants<Paragraph>())
            {
                if (word.Length == 0 && words.Count > 0)
                {
                    string data = words.Dequeue();
                    if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@";
                    word.Append(data);
                }
                foreach (OpenXmlElement runOrHyperLink in paragraph.Elements())
                {
                    if (runOrHyperLink is Hyperlink)
                    {
                        foreach (Run run in runOrHyperLink.Elements<Run>())
                        {
                            HandleTranslateRun(run, word, words, runInstances);
                        }
                    }
                    else if (runOrHyperLink is Run)
                    {
                        HandleTranslateRun((Run)runOrHyperLink, word, words, runInstances);
                    }
                }
            }
        }

        public static void HandleTranslateRun(Run run, StringBuilder word, Queue<string> words, List<Run> runInstances)
        {
            if (runInstances.Contains(run)) return;
            runInstances.Add(run);
            if (!run.Elements<Text>().Any() && (run.Descendants<TabChar>().Any() || run.Descendants<Text>().Any()))
            {
                ReplaceText(run, words, runInstances, word);
                if (word.Length == 0 && words.Count > 0)
                {
                    string data = words.Dequeue();
                    if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@";
                    word.Append(data);
                }
            }
            else
            {
                foreach (var item in run.ChildElements)
                {
                    if (item is TabChar)
                    {
                        if (word.Length == 0 && words.Count > 0)
                        {
                            string data = words.Dequeue();
                            if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@";
                            word.Append(data);
                        }
                    }
                    else if (item is Text)
                    {
                        ((Text)item).Text = word.ToString() == "@@@This_is_the_empty_replace@@@" ? "" : word.ToString();
                        word.Clear();
                    }
                }
            }
        }
    }
}