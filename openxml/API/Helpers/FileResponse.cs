namespace API.Helpers
{
    public class FileResponse : FileStream
    {
        readonly string path;

        public FileResponse(string path, FileMode mode) : base(path, mode)
        {
            this.path = path;
        }

        protected override void Dispose(bool disposing)
        {
            base.Dispose(disposing);
            if (disposing)
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
            }
        }
    }
}
