# Chaincode-as-a-Service container. Uses vendored Go dependencies.
# Server mode is selected by CHAINCODE_SERVER_ADDRESS.

FROM golang:1.21-alpine AS build
WORKDIR /src
COPY . .
# vendor/ is present (go mod vendor), so the build needs no network.
RUN CGO_ENABLED=0 go build -mod=vendor -o /chaincode .

FROM alpine:3.19
RUN adduser -D -u 10000 chaincode
COPY --from=build /chaincode /usr/local/bin/chaincode
USER chaincode
ARG CC_SERVER_PORT=9999
EXPOSE ${CC_SERVER_PORT}
CMD ["/usr/local/bin/chaincode"]
