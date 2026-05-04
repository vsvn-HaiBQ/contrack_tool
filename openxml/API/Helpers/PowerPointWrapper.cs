using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Drawing;
using DocumentFormat.OpenXml.Packaging;
using Presentation = DocumentFormat.OpenXml.Presentation;
using System.Text;

namespace API.Helpers
{
    public static class PowerPointWrapper
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
            List<string> words = new List<string>();
            StringBuilder word = new StringBuilder();
            List<Run> runInstance = new List<Run>();

            using (PresentationDocument document = PresentationDocument.Open(filePath, false))
            {
                PresentationPart? presentationPart = document.PresentationPart;
                Presentation.SlideIdList? slideIdList = presentationPart?.Presentation?.SlideIdList;

                if (presentationPart != null && slideIdList != null)
                {
                    foreach (Presentation.SlideId slideId in slideIdList)
                    {
                        if (slideId.RelationshipId != null)
                        {
                            OpenXmlPart part = presentationPart.GetPartById(slideId.RelationshipId!);
                            Presentation.Slide slide = (part as SlidePart)!.Slide;
                            foreach (Paragraph paragraph in slide.Descendants<Paragraph>())
                            {
                                foreach (OpenXmlElement item in paragraph.Elements())
                                {
                                    if (item is Run)
                                    {
                                        if (runInstance.Contains((item as Run)!)) continue;
                                        runInstance.Add((item as Run)!);
                                        foreach (Text text in item.Elements<Text>())
                                        {
                                            word.Append(text.Text);
                                        }
                                    }
                                    else
                                    {
                                        if (word.Length > 0)
                                        {
                                            words.Add(word.ToString());
                                            word.Clear();
                                        }
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
                }
            }
            return words;
        }

        public static void Translate(string filePath, Queue<string> trans)
        {
            StringBuilder word = new StringBuilder();
            List<Run> runInstance = new List<Run>();

            using (PresentationDocument document = PresentationDocument.Open(filePath, true))
            {
                PresentationPart? presentationPart = document.PresentationPart;
                Presentation.SlideIdList? slideIdList = presentationPart?.Presentation?.SlideIdList;

                if (presentationPart != null && slideIdList != null)
                {
                    foreach (Presentation.SlideId slideId in slideIdList)
                    {
                        if (slideId.RelationshipId != null)
                        {
                            OpenXmlPart part = presentationPart.GetPartById(slideId.RelationshipId!);
                            Presentation.Slide slide = (part as SlidePart)!.Slide;
                            foreach (Paragraph paragraph in slide.Descendants<Paragraph>())
                            {
                                if (word.Length == 0 && trans.Count > 0)
                                {
                                    string data = trans.Dequeue();
                                    if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@@";
                                    word.Append(data);
                                }
                                foreach (OpenXmlElement item in paragraph.Elements())
                                {
                                    if (item is Run)
                                    {
                                        if (runInstance.Contains((item as Run)!)) continue;
                                        runInstance.Add((item as Run)!);
                                        foreach (Text text in item.Elements<Text>())
                                        {
                                            text.Text = word.ToString() == "@@@This_is_the_empty_replace@@@@" ? "" : word.ToString();
                                            word.Clear();
                                        }
                                    }
                                    else
                                    {
                                        if (word.Length == 0 && trans.Count > 0)
                                        {
                                            string data = trans.Dequeue();
                                            if (data == null || data.Length == 0) data = "@@@This_is_the_empty_replace@@@@";
                                            word.Append(data);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                document.Save();
            }
        }
    }
}
