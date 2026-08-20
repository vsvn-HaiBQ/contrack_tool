using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Drawing;
using DocumentFormat.OpenXml.Packaging;
using Diagram = DocumentFormat.OpenXml.Drawing.Diagrams;
using Presentation = DocumentFormat.OpenXml.Presentation;
using System.Xml.Linq;

namespace API.Helpers
{
    public static class PowerPointWrapper
    {
        private const string EmptyReplacementMarker = "@@@This_is_the_empty_replace@@@@";

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
                            SlidePart slidePart = (presentationPart.GetPartById(slideId.RelationshipId!) as SlidePart)!;
                            foreach (Paragraph paragraph in GetTextParagraphs(slidePart))
                            {
                                foreach (List<Text> textSegment in GetTextSegments(paragraph))
                                {
                                    string text = string.Concat(textSegment.Select(item => item.Text));
                                    if (text.Length > 0)
                                    {
                                        words.Add(text);
                                    }
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
            using (PresentationDocument document = PresentationDocument.Open(filePath, true))
            {
                List<SlidePart> translatedSlides = new List<SlidePart>();
                PresentationPart? presentationPart = document.PresentationPart;
                Presentation.SlideIdList? slideIdList = presentationPart?.Presentation?.SlideIdList;

                if (presentationPart != null && slideIdList != null)
                {
                    foreach (Presentation.SlideId slideId in slideIdList)
                    {
                        if (slideId.RelationshipId != null)
                        {
                            SlidePart slidePart = (presentationPart.GetPartById(slideId.RelationshipId!) as SlidePart)!;
                            foreach (Paragraph paragraph in GetTextParagraphs(slidePart))
                            {
                                foreach (List<Text> textSegment in GetTextSegments(paragraph))
                                {
                                    string sourceText = string.Concat(textSegment.Select(item => item.Text));
                                    if (sourceText.Length == 0 || trans.Count == 0)
                                    {
                                        continue;
                                    }

                                    string replacement = trans.Dequeue();
                                    if (string.IsNullOrEmpty(replacement))
                                    {
                                        replacement = EmptyReplacementMarker;
                                    }

                                    textSegment[0].Text = replacement == EmptyReplacementMarker ? string.Empty : replacement;
                                    for (int i = 1; i < textSegment.Count; i++)
                                    {
                                        textSegment[i].Text = string.Empty;
                                    }
                                }
                            }

                            translatedSlides.Add(slidePart);
                        }
                    }
                }
                document.Save();

                foreach (SlidePart slidePart in translatedSlides.Distinct())
                {
                    SynchronizeSmartArtDrawingCache(slidePart);
                }
            }
        }

        /// <summary>
        /// Gets paragraphs in the slide's visual order. Text in a PowerPoint text box or
        /// placeholder lives in a Presentation.Shape.TextBody, not directly on the slide.
        /// Graphic frames are included to retain support for text in tables and SmartArt.
        /// </summary>
        private static IEnumerable<Paragraph> GetTextParagraphs(SlidePart slidePart)
        {
            Presentation.Slide slide = slidePart.Slide;
            Presentation.ShapeTree? shapeTree = slide.CommonSlideData?.ShapeTree;
            if (shapeTree == null)
            {
                yield break;
            }

            foreach (OpenXmlElement element in shapeTree.Descendants())
            {
                if (element is Presentation.Shape { TextBody: not null } shape)
                {
                    foreach (Paragraph paragraph in shape.TextBody!.Elements<Paragraph>())
                    {
                        yield return paragraph;
                    }
                }
                else if (element is Presentation.GraphicFrame graphicFrame)
                {
                    foreach (Paragraph paragraph in graphicFrame.Descendants<Paragraph>())
                    {
                        yield return paragraph;
                    }

                    foreach (Paragraph paragraph in GetSmartArtParagraphs(slidePart, graphicFrame))
                    {
                        yield return paragraph;
                    }
                }
            }
        }

        /// <summary>
        /// Resolves the data part referenced by a SmartArt graphic frame. SmartArt keeps its
        /// editable text in a DiagramDataPart instead of the slide XML.
        /// </summary>
        private static IEnumerable<Paragraph> GetSmartArtParagraphs(SlidePart slidePart, Presentation.GraphicFrame graphicFrame)
        {
            Diagram.RelationshipIds? relationshipIds = graphicFrame.Graphic?.GraphicData?.GetFirstChild<Diagram.RelationshipIds>();
            if (relationshipIds?.DataPart?.Value is not string dataPartRelationshipId)
            {
                yield break;
            }

            if (slidePart.GetPartById(dataPartRelationshipId) is not DiagramDataPart diagramDataPart ||
                diagramDataPart.DataModelRoot == null)
            {
                yield break;
            }

            foreach (Paragraph paragraph in diagramDataPart.DataModelRoot.Descendants<Paragraph>())
            {
                yield return paragraph;
            }
        }

        /// <summary>
        /// Synchronizes SmartArt's generated drawing cache with its editable data model.
        /// PowerPoint stores the editable text in data*.xml and the rendered text in
        /// drawing*.xml; updating both ensures the exported file displays the translation.
        /// </summary>
        private static void SynchronizeSmartArtDrawingCache(SlidePart slidePart)
        {
            Dictionary<string, List<string>> textByModelId = new Dictionary<string, List<string>>();
            foreach (DiagramDataPart diagramDataPart in slidePart.DiagramDataParts)
            {
                if (diagramDataPart.DataModelRoot == null)
                {
                    continue;
                }

                List<Diagram.Point> points = diagramDataPart.DataModelRoot.Descendants<Diagram.Point>().ToList();
                foreach (Diagram.Point point in points)
                {
                    if (point.ModelId?.Value is not string modelId || point.TextBody == null)
                    {
                        continue;
                    }

                    textByModelId[modelId] = point.TextBody.Descendants<Text>().Select(text => text.Text).ToList();
                }

                // The rendered SmartArt shape uses a presentation point's model ID. Its
                // presAssocID points back to the data point containing the editable text.
                foreach (Diagram.Point point in points)
                {
                    if (point.ModelId?.Value is not string renderedModelId ||
                        point.PropertySet?.PresentationElementId?.Value is not string dataModelId ||
                        !textByModelId.TryGetValue(dataModelId, out List<string>? sourceTexts))
                    {
                        continue;
                    }

                    textByModelId[renderedModelId] = sourceTexts;
                }
            }

            if (textByModelId.Count == 0)
            {
                return;
            }

            XNamespace drawingNamespace = "http://schemas.microsoft.com/office/drawing/2008/diagram";
            XNamespace textNamespace = "http://schemas.openxmlformats.org/drawingml/2006/main";

            foreach (IdPartPair relationship in slidePart.Parts)
            {
                if (relationship.OpenXmlPart.RelationshipType != "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing")
                {
                    continue;
                }

                XDocument drawing;
                using (Stream stream = relationship.OpenXmlPart.GetStream(FileMode.Open, FileAccess.Read))
                {
                    drawing = XDocument.Load(stream);
                }

                bool changed = false;
                foreach (XElement shape in drawing.Descendants(drawingNamespace + "sp"))
                {
                    string? modelId = (string?)shape.Attribute("modelId");
                    if (modelId == null || !textByModelId.TryGetValue(modelId, out List<string>? sourceTexts))
                    {
                        continue;
                    }

                    List<XElement> renderedTexts = shape.Descendants(textNamespace + "t").ToList();
                    if (renderedTexts.Count != sourceTexts.Count)
                    {
                        continue;
                    }

                    for (int i = 0; i < renderedTexts.Count; i++)
                    {
                        if (renderedTexts[i].Value != sourceTexts[i])
                        {
                            renderedTexts[i].Value = sourceTexts[i];
                            changed = true;
                        }
                    }
                }

                if (changed)
                {
                    using Stream stream = relationship.OpenXmlPart.GetStream(FileMode.Create, FileAccess.Write);
                    drawing.Save(stream);
                }
            }
        }

        /// <summary>
        /// Splits paragraph text at PowerPoint line breaks and returns the text nodes that
        /// belong to each translatable segment. A field is handled as its own segment.
        /// </summary>
        private static IEnumerable<List<Text>> GetTextSegments(Paragraph paragraph)
        {
            List<Text> textSegment = new List<Text>();

            foreach (OpenXmlElement element in paragraph.ChildElements)
            {
                if (element is Run)
                {
                    textSegment.AddRange(element.Elements<Text>());
                    continue;
                }

                if (textSegment.Count > 0)
                {
                    yield return textSegment;
                    textSegment = new List<Text>();
                }

                if (element is Field)
                {
                    List<Text> fieldText = element.Elements<Text>().ToList();
                    if (fieldText.Count > 0)
                    {
                        yield return fieldText;
                    }
                }
            }

            if (textSegment.Count > 0)
            {
                yield return textSegment;
            }
        }
    }
}
