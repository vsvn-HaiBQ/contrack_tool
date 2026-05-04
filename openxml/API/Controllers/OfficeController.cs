using Amazon.S3;
using Amazon.S3.Model;
using Amazon.S3.Util;
using API.Helpers;
using Microsoft.AspNetCore.Mvc;
using System.Net.Mime;

namespace API.Controllers
{
    [Route("/")]
    public class OfficeController : Controller
    {
        // private readonly IAmazonS3 _s3Client;
        // public OfficeController(IAmazonS3 s3Client)
        // {
        //     _s3Client = s3Client;
        // }

        [HttpPost("import")]
        public IActionResult Import(IFormFile file, List<string> sheets)
        {
            if (file == null || file.Length == 0)
            {
                return BadRequest("No file selected");
            }

            string extension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (string.IsNullOrEmpty(extension) || (extension != ".xlsx" && extension != ".docx" && extension != ".pptx"))
            {
                return BadRequest("Invalid file type");
            }

            using (var stream = file.OpenReadStream())
            {
                List<string> words = new List<string>();
                switch (extension)
                {
                    case ".xlsx":
                        words = ExcelWrapper.GetWords(stream, sheets);
                        break;
                    case ".docx":
                        words = WordWrapper.GetWords(stream);
                        break;
                    case ".pptx":
                        words = PowerPointWrapper.GetWords(stream);
                        break;
                }
                return Ok(words);
            }
        }

        [HttpPost("export")]
        public async Task<IActionResult> Export(IFormFile file, List<string> data, List<string> sheets)
        {
            if (file == null || file.Length == 0)
            {
                return BadRequest("No file selected");
            }

            string extension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (string.IsNullOrEmpty(extension) || (extension != ".xlsx" && extension != ".docx" && extension != ".pptx"))
            {
                return BadRequest("Invalid file type");
            }

            string newFileName = Path.GetRandomFileName() + extension;
            string folderPath = Path.Combine(Directory.GetCurrentDirectory(), "wwwroot");
            if (!Directory.Exists(folderPath))
            {
                Directory.CreateDirectory(folderPath);
            }

            string filePath = Path.Combine(folderPath, newFileName);
            using (var stream = new FileStream(filePath, FileMode.Create))
            {
                await file.CopyToAsync(stream);
            }

            Queue<string> trans = new Queue<string>(data);
            switch (extension)
            {
                case ".xlsx":
                    ExcelWrapper.Translate(filePath, trans, sheets);
                    break;
                case ".docx":
                    WordWrapper.Translate(filePath, trans);
                    break;
                case ".pptx":
                    PowerPointWrapper.Translate(filePath, trans);
                    break;
            }

            return File(new FileResponse(filePath, FileMode.Open), MediaTypeNames.Application.Octet);
        }

        [HttpPost("judge")]
        public IActionResult Judge(IFormFile file)
        {
            if (file == null || file.Length == 0)
            {
                return BadRequest("No file selected");
            }

            string extension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (string.IsNullOrEmpty(extension) || (extension != ".xlsx"))
            {
                return BadRequest("Invalid file type");
            }

            using (var stream = file.OpenReadStream())
            {
                List<string> words = new List<string>();
                words = ExcelWrapper.SheetNames(stream);
                return Ok(words);
            }
        }

        // [HttpPost("preview")]
        // public async Task<IActionResult> GetAllBucketAsync(IFormFile file, List<string> data, List<string> sheets)
        // {
        //     if (file == null || file.Length == 0)
        //     {
        //         return BadRequest("No file selected");
        //     }

        //     string extension = Path.GetExtension(file.FileName).ToLowerInvariant();
        //     if (string.IsNullOrEmpty(extension) || (extension != ".xlsx" && extension != ".docx" && extension != ".pptx"))
        //     {
        //         return BadRequest("Invalid file type");
        //     }

        //     var bucketExists = await AmazonS3Util.DoesS3BucketExistV2Async(_s3Client, "office-preview");
        //     if (!bucketExists) return NotFound("Bucket office-preview does not exist.");

        //     string fileName = Guid.NewGuid().ToString("N") + extension;

        //     string folderPath = Path.Combine(Directory.GetCurrentDirectory(), "wwwroot");
        //     if (!Directory.Exists(folderPath))
        //     {
        //         Directory.CreateDirectory(folderPath);
        //     }

        //     string filePath = Path.Combine(folderPath, fileName);
        //     using (var stream = new FileStream(filePath, FileMode.Create))
        //     {
        //         await file.CopyToAsync(stream);
        //     }

        //     Queue<string> trans = new Queue<string>(data);
        //     switch (extension)
        //     {
        //         case ".xlsx":
        //             ExcelWrapper.Translate(filePath, trans, sheets);
        //             break;
        //         case ".docx":
        //             WordWrapper.Translate(filePath, trans);
        //             break;
        //         case ".pptx":
        //             PowerPointWrapper.Translate(filePath, trans);
        //             break;
        //     }

        //     var request = new PutObjectRequest()
        //     {
        //         BucketName = "office-preview",
        //         Key = fileName,
        //         InputStream = System.IO.File.OpenRead(filePath)
        //     };
        //     request.Metadata.Add("Content-Type", file.ContentType);
        //     await _s3Client.PutObjectAsync(request);
        //     string url = $"https://view.officeapps.live.com/op/view.aspx?src=https://d1yu176hq7h4mx.cloudfront.net/{fileName}";

        //     new Timer(async (state) =>
        //     {
        //         if (System.IO.File.Exists(filePath))
        //         {
        //             System.IO.File.Delete(filePath);
        //         }
        //         var deleteObjectRequest = new DeleteObjectRequest
        //         {
        //             BucketName = "office-preview",
        //             Key = fileName
        //         };
        //         await _s3Client.DeleteObjectAsync(deleteObjectRequest);
        //     }, null, 300000, Timeout.Infinite);

        //     return Ok(url);
        // }
    }
}
