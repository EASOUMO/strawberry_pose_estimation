

#include <iostream>
#include <sstream>
#include <boost/program_options.hpp>
#include <boost/lexical_cast.hpp>
#include <boost/random.hpp>

#include <time.h>

#pragma warning( push )
#pragma warning( disable : 4242 )
#include <boost/asio.hpp>
#pragma warning( pop )


int main( int argc, char *argv[] )
{
  std::string CaptureName;
  std::string CaptureNotes;
  std::string CaptureDescription;
  std::string CaptureDatabasePath;
  std::string Timecode;
  unsigned int CaptureDelayInMilliseconds = 0;
  unsigned short Port = 30;

  // Parse out the options from the command line.
  // The name and path are mandatory for both the start and stop signals.

  boost::program_options::options_description Description("Allowed options");
  Description.add_options()
      ("help", "Show help message")
      ("start", "Send start signal")
      ("stop", "Send stop signal")

      ("name", boost::program_options::value< std::string >( &CaptureName )->required(), "The name trial to capture (required)" )
      ("notes", boost::program_options::value< std::string >( &CaptureNotes ), "The notes associated with the trial" )
      ("description", boost::program_options::value< std::string >( &CaptureDescription ), "The description of the trial" )
      ("path", boost::program_options::value< std::string >( &CaptureDatabasePath )->required(), "The database capture path (required)" )

      ("timecode", boost::program_options::value< std::string >( &Timecode ), "A timecode to start / stop on" )
      ("delay", boost::program_options::value< unsigned int >( &CaptureDelayInMilliseconds ), "A delay in milliseconds before capture" )

      ("port", boost::program_options::value< unsigned short >( &Port ), "The port to broadcast on" )
  ;

  boost::program_options::variables_map Variables;

  try
  {
    boost::program_options::store( boost::program_options::parse_command_line(argc, argv, Description), Variables );
  }
  catch( boost::program_options::invalid_option_value Exception )
  {
    std::cout << Description << std::endl;
    return 1;
  }

  try
  {
    boost::program_options::notify( Variables );
  }
  catch( boost::program_options::required_option Exception )
  {
    std::cout << Description << std::endl;
    std::cout << "--name and --path are required." << std::endl;

    return 1;
  }

  if( Variables.count("help") ) 
  {
    std::cout << Description << std::endl;
    return 1;
  }

  // One of stop or start should have been specified

  if( Variables.count("start") + Variables.count("stop") != 1 ) 
  {
    std::cout << "Usage:" << std::endl;
    std::cout << argv[0] << " --start --name Test --description \"Captured automatically.\" --path \"C:/Temp\"" << std::endl;
    std::cout << argv[0] << " --stop --name Test --path \"C:/Temp\"" << std::endl;
    return 1;
  }

  // Seed the random number with the time.
  boost::rand48 Random( 100000 );
  Random.seed( static_cast< boost::rand48::result_type >( time(0) ) );

  // The packet ID is selected randomly.
  // Packets with duplicate ID's are ignored by Nexus.
  const unsigned int CaptureID = Random();

  //.Set up ASIO for UDP broadcast.
  boost::asio::io_service Service;

  // Create and open socket.
  boost::asio::ip::udp::socket Socket( Service );

  boost::system::error_code Error;
  Socket.open( boost::asio::ip::udp::v4(), Error );
  
  if( !Error )
  {
    // Successfully opened the socket.
    // Set to broadcast.
    Socket.set_option( boost::asio::ip::udp::socket::reuse_address(true) );
    Socket.set_option( boost::asio::socket_base::broadcast(true) );

    boost::asio::ip::udp::endpoint SenderEndpoint( boost::asio::ip::address_v4::broadcast(), Port );
    
    // Build up XML contents of the broadcast message.

    std::ostringstream Stream;

    // Start capture.
    if( Variables.count("start") )
    {
      Stream << "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>" << std::endl;
      Stream << "<CaptureStart>" << std::endl;
      Stream << "  <Name VALUE=\"" << CaptureName << "\"/>" << std::endl;
      if( !CaptureNotes.empty() )
        Stream << "  <Notes VALUE=\"" << CaptureNotes << "\"/>" << std::endl;
      if( !CaptureDescription.empty() )
        Stream << "  <Description VALUE=\"" << CaptureDescription << "\"/>" << std::endl;
      if( !Timecode.empty() )
        Stream << "  <TimeCode VALUE=\"" << Timecode << "\"/>" << std::endl;
      Stream << "  <DatabasePath VALUE=\"" << CaptureDatabasePath << "\"/>" << std::endl;
      Stream << "  <Delay VALUE=\"" << CaptureDelayInMilliseconds << "\"/>" << std::endl;
      Stream << "  <PacketID VALUE=\"" << CaptureID << "\"/>" << std::endl;
      Stream << "</CaptureStart>" << std::endl;
    }

    // Stop capture.
    if( Variables.count("stop") )
    {
      Stream << "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>" << std::endl;
      Stream << "<CaptureStop>" << std::endl;
      Stream << "  <Name VALUE=\"" << CaptureName << "\"/>" << std::endl;
      Stream << "  <DatabasePath VALUE=\"" << CaptureDatabasePath << "\"/>" << std::endl;
      if( !Timecode.empty() )
        Stream << "  <TimeCode VALUE=\"" << Timecode << "\"/>" << std::endl;
      Stream << "  <PacketID VALUE=\"" << CaptureID << "\"/>" << std::endl;
      Stream << "</CaptureStop>" << std::endl;
    }

    std::string String( Stream.str() );

    // Send message.
    // Buffer must contain terminating 0.
    Socket.send_to( boost::asio::buffer( String.c_str(), String.size() + 1 ), SenderEndpoint );
    Socket.close( Error );
  }

  return Error.value();
}
