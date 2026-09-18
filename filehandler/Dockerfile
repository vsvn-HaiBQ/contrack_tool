FROM mcr.microsoft.com/dotnet/sdk:10.0.401-alpine AS build
WORKDIR /src
COPY global.json Directory.Build.props NuGet.Config ./
COPY src/FileHandler.Api/FileHandler.Api.csproj src/FileHandler.Api/
RUN dotnet restore src/FileHandler.Api/FileHandler.Api.csproj
COPY src/ src/
RUN dotnet publish src/FileHandler.Api/FileHandler.Api.csproj -c Release --no-restore -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS final
WORKDIR /app
ENV ASPNETCORE_HTTP_PORTS=5001
EXPOSE 5001
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "FileHandler.Api.dll"]
